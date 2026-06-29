console.log("=== FILE BOOTSTRAP V9 ĐÃ CHẠY ===");

window.addEventListener("load", async function () {
  console.log("=== WINDOW LOAD ĐÃ CHẠY ===");

  var configNode = document.getElementById("web3auth-config");
  var badge = document.getElementById("walletAddressBadge");
  var guestButton = document.getElementById("google-login-btn");
  var authButton = document.getElementById("web3authGoogleBtn");
  var logoutAllBtn = document.getElementById("logoutAllBtn");
  var djangoLogoutForm = document.getElementById("djangoLogoutForm");
  var candidateButtons = Array.prototype.slice.call(
    document.querySelectorAll("[data-web3auth-google]")
  );

  console.log("[DCP][Web3Auth] google-login-btn =", guestButton);
  console.log("[DCP][Web3Auth] web3authGoogleBtn =", authButton);
  console.log("[DCP][Web3Auth] buttons with [data-web3auth-google] =", candidateButtons.length);

  var config = {};
  if (configNode) {
    try {
      config = JSON.parse(configNode.textContent);
    } catch (error) {
      console.error("[DCP][Web3Auth] parse config lỗi:", error);
    }
  }

  function debugLog() {
    var args = Array.prototype.slice.call(arguments);
    args.unshift("[DCP][Web3Auth]");
    console.log.apply(console, args);
  }

  function shortenAddress(address) {
    if (!address || address.length < 10) return address || "";
    return address.slice(0, 6) + "..." + address.slice(-4);
  }

  function updateWalletBadge(address) {
    if (!badge) return;
    badge.dataset.walletAddress = address || "";
    badge.textContent = address ? "Ví Google: " + shortenAddress(address) : "Chưa kết nối ví";
  }

  function showToast(message) {
    if (typeof window.dismissToast !== "function") {
      alert(message);
      return;
    }
    var container = document.getElementById("toastContainer");
    if (!container) {
      alert(message);
      return;
    }
    var toast = document.createElement("div");
    toast.className = "toast-notification toast-info";
    toast.innerHTML =
      '<div class="toast-icon"><i class="fas fa-info-circle"></i></div>' +
      '<div class="toast-body"></div>' +
      '<button class="toast-close" type="button">&times;</button>' +
      '<div class="toast-progress"></div>';
    toast.querySelector(".toast-body").textContent = message;
    toast.querySelector(".toast-close").addEventListener("click", function () {
      window.dismissToast(toast);
    });
    container.appendChild(toast);
    requestAnimationFrame(function () {
      toast.classList.add("show");
    });
  }

  function getCookie(name) {
    var value = "; " + document.cookie;
    var parts = value.split("; " + name + "=");
    if (parts.length === 2) {
      return parts.pop().split(";").shift();
    }
    return "";
  }

  async function resolveAddressFromProvider(provider) {
    if (!provider) return "";
    var accounts = await provider.request({ method: "eth_accounts" });
    console.log("[DCP][Web3Auth] hydrate/accounts =", accounts);
    return Array.isArray(accounts) && accounts[0] ? accounts[0] : "";
  }

  async function postJson(url, payload) {
    var response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCookie("csrftoken"),
      },
      credentials: "same-origin",
      body: JSON.stringify(payload),
    });
    var data = await response.json();
    if (!response.ok || data.ok === false) {
      throw new Error(data.message || ("Request failed: " + url));
    }
    return data;
  }

  function clearWeb3AuthStorage() {
    [window.localStorage, window.sessionStorage].forEach(function (store) {
      if (!store) return;
      Object.keys(store)
        .filter(function (key) {
          return /web3auth|openlogin|auth/i.test(key);
        })
        .forEach(function (key) {
          store.removeItem(key);
        });
    });
  }

  async function logoutAllSessions(event) {
    if (event) event.preventDefault();
    console.log("[DCP][Web3Auth] bắt đầu logout tất cả session...");
    if (typeof window.showLoader === "function") window.showLoader();

    try {
      if (web3auth && typeof web3auth.logout === "function") {
        await web3auth.logout();
        console.log("[DCP][Web3Auth] logout Web3Auth thành công.");
      }
    } catch (logoutError) {
      console.warn("[DCP][Web3Auth] logout Web3Auth lỗi nhưng vẫn tiếp tục dọn cache:", logoutError);
    }

    clearWeb3AuthStorage();
    console.log("[DCP][Web3Auth] đã xóa cache Web3Auth trong browser.");

    if (djangoLogoutForm) {
      djangoLogoutForm.submit();
      return;
    }

    window.location.href = "/admin/dangxuat/";
  }

  var Web3AuthClass =
    window.NoModal &&
    (window.NoModal.Web3AuthNoModal || window.NoModal.Web3Auth);

  var ProviderClass =
    window.EthereumProvider &&
    window.EthereumProvider.EthereumPrivateKeyProvider;

  var AuthAdapterClass =
    window.AuthAdapter &&
    window.AuthAdapter.AuthAdapter;

  console.log("[DCP][Web3Auth] class availability =", {
    hasWeb3AuthClass: !!Web3AuthClass,
    hasProviderClass: !!ProviderClass,
    hasAuthAdapterClass: !!AuthAdapterClass,
    noModalKeys: Object.keys(window.NoModal || {}),
    ethereumProviderKeys: Object.keys(window.EthereumProvider || {}),
    authAdapterKeys: Object.keys(window.AuthAdapter || {}),
  });

  if (!Web3AuthClass || !ProviderClass || !AuthAdapterClass) {
    console.error("[DCP][Web3Auth] FATAL: thiếu class v9.");
    return;
  }

  var clientId =
    config.clientId ||
    config.client_id ||
    "";

  if (!clientId) {
    console.error("[DCP][Web3Auth] Thiếu clientId trong web3auth-config.");
    return;
  }

  var chainConfig = {
    chainNamespace: "eip155",
    chainId: "0xaa36a7",
    rpcTarget: config.rpcTarget || "https://rpc.ankr.com/eth_sepolia",
    displayName: config.displayName || "Ethereum Sepolia",
    blockExplorerUrl: config.blockExplorerUrl || "https://sepolia.etherscan.io",
    ticker: config.ticker || "ETH",
    tickerName: config.tickerName || "Ethereum",
  };

  var privateKeyProvider = null;
  var web3auth = null;

  try {
    privateKeyProvider = new ProviderClass({
      config: { chainConfig: chainConfig },
    });

    web3auth = new Web3AuthClass({
      clientId: clientId,
      web3AuthNetwork: config.network || "sapphire_mainnet",
      chainConfig: chainConfig,
      privateKeyProvider: privateKeyProvider,
      sessionTime: 604800,
    });

    var authAdapter = new AuthAdapterClass({
      adapterSettings: {
        uxMode: "popup",
        redirectUrl: window.location.origin,
      },
    });

    web3auth.configureAdapter(authAdapter);
    console.log("[DCP][Web3Auth] adapter configured");

    await web3auth.init();
    console.log("[DCP][Web3Auth] init xong. status =", web3auth.status);

    if (web3auth.provider) {
      console.log("[DCP][Web3Auth] phát hiện provider sau init, đang hydrate session...");
      var hydratedAddress = await resolveAddressFromProvider(web3auth.provider);
      if (hydratedAddress) {
        console.log("[DCP][Web3Auth] hydrate thành công. address =", hydratedAddress);
        updateWalletBadge(hydratedAddress);
        
        // Kiểm tra xem URL có hash từ redirect về hay không
        // Nếu có, đây là luồng vừa login xong, cần đẩy dữ liệu lên Django
        if (window.location.hash.includes("access_token") || window.location.hash.includes("state")) {
            console.log("[DCP][Web3Auth] Phát hiện redirect hash, tự động đồng bộ session...");
            
            // Xóa hash trên URL để URL sạch đẹp hơn
            history.replaceState(null, null, ' ');
            
            var userInfo = {};
            if (typeof web3auth.getUserInfo === "function") {
                try {
                    userInfo = await web3auth.getUserInfo();
                } catch (e) {
                    console.warn("[DCP][Web3Auth] getUserInfo sau redirect lỗi:", e);
                }
            }

            try {
                if (typeof window.showLoader === "function") window.showLoader();
                showToast("Đang đồng bộ ví Web3...");
                await postJson("/api/auth/web3-login/", {
                    wallet_address: hydratedAddress,
                    eoa_address: hydratedAddress,
                    email: userInfo.email || "",
                    display_name: userInfo.name || userInfo.email || "",
                    provider: "web3auth_google",
                });

                await postJson("/api/auth/wallet-sync/", {
                    wallet_address: hydratedAddress,
                    eoa_address: hydratedAddress,
                    smart_account_address: hydratedAddress,
                    provider: "web3auth_google",
                });
                
                showToast("Đăng nhập Web3 thành công!");
                setTimeout(function() { window.location.reload(); }, 1000);
            } catch (err) {
                if (typeof window.hideLoader === "function") window.hideLoader();
                console.error("[DCP][Web3Auth] Đồng bộ session sau redirect lỗi:", err);
                showToast("Lỗi đồng bộ dữ liệu. Vui lòng thử lại.");
            }
        }
      } else {
        console.log("[DCP][Web3Auth] session có provider nhưng chưa lấy được address.");
      }
    } else {
      console.log("[DCP][Web3Auth] sau init chưa có provider.");
    }
  } catch (error) {
    console.error("[DCP][Web3Auth] init lỗi:", error);
    return;
  }

  async function handleLoginClick(event) {
    event.preventDefault();
    console.log("[DCP][Web3Auth] 1. ĐÃ BẤM NÚT LOGIN");
    if (typeof window.showLoader === "function") window.showLoader();

    try {
      console.log("[DCP][Web3Auth] 2. status trước connect =", web3auth.status);
      var provider = null;

      if (web3auth.connected || web3auth.status === "connected") {
        console.log("[DCP][Web3Auth] 2a. Đã có session sẵn, thử dùng provider hiện tại...");
        provider = web3auth.provider;

        if (!provider) {
          console.log("[DCP][Web3Auth] 2b. Connected nhưng provider rỗng, logout để dọn session kẹt...");
          await web3auth.logout();
          provider = await web3auth.connectTo("auth", {
            loginProvider: "google",
          });
        }
      } else {
        provider = await web3auth.connectTo("auth", {
          loginProvider: "google",
        });
      }

      console.log("[DCP][Web3Auth] 3. provider sau connect =", provider);

      if (!provider) {
        throw new Error("Web3Auth không trả về provider.");
      }

      var address = await resolveAddressFromProvider(provider);
      if (address) {
        updateWalletBadge(address);
      } else {
        console.log("[DCP][Web3Auth] 4. Không lấy được address từ provider.");
      }

      var userInfo = {};
      if (typeof web3auth.getUserInfo === "function") {
        try {
          userInfo = await web3auth.getUserInfo();
          console.log("[DCP][Web3Auth] 4b. userInfo =", userInfo);
        } catch (userInfoError) {
          console.warn("[DCP][Web3Auth] Không lấy được userInfo:", userInfoError);
        }
      }

      console.log("[DCP][Web3Auth] 4c. Đang tạo Django session...");
      await postJson("/api/auth/web3-login/", {
        wallet_address: address,
        eoa_address: address,
        email: userInfo.email || "",
        display_name: userInfo.name || userInfo.email || "",
        provider: "web3auth_google",
      });

      console.log("[DCP][Web3Auth] 4d. Đang đồng bộ ví vào profile...");
      await postJson("/api/auth/wallet-sync/", {
        wallet_address: address,
        eoa_address: address,
        smart_account_address: address,
        provider: "web3auth_google",
      });

      alert("Login Successful");
      window.location.reload();
    } catch (error) {
      if (typeof window.hideLoader === "function") window.hideLoader();
      console.error("[DCP][Web3Auth] 5. login lỗi:", error);
      showToast(error && error.message ? error.message : "Đăng nhập thất bại");
    }
  }

  var buttonsToBind = [];
  if (guestButton) buttonsToBind.push(guestButton);
  if (authButton && authButton !== guestButton) buttonsToBind.push(authButton);

  candidateButtons.forEach(function (button) {
    if (buttonsToBind.indexOf(button) === -1) {
      buttonsToBind.push(button);
    }
  });

  console.log("[DCP][Web3Auth] buttonsToBind =", buttonsToBind.length, buttonsToBind);

  buttonsToBind.forEach(function (button) {
    if (!button) return;
    if (button.dataset.web3authBound === "true") return;
    button.dataset.web3authBound = "true";
    button.addEventListener("click", handleLoginClick);
    console.log("[DCP][Web3Auth] bound click for button id =", button.id || "(no-id)");
  });

  if (logoutAllBtn) {
    logoutAllBtn.addEventListener("click", logoutAllSessions);
    console.log("[DCP][Web3Auth] bound logoutAllBtn");
  }

  window.dcpWeb3 = {
    web3auth: web3auth,
    handleLoginClick: handleLoginClick,
    logoutAllSessions: logoutAllSessions,
  };

  debugLog("bootstrap ready");
});
