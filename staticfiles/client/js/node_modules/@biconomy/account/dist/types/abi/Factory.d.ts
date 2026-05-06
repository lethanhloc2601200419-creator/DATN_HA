export declare const BiconomyFactoryAbi: readonly [{
    readonly anonymous: false;
    readonly inputs: readonly [{
        readonly indexed: true;
        readonly internalType: "address";
        readonly name: "account";
        readonly type: "address";
    }, {
        readonly indexed: true;
        readonly internalType: "address";
        readonly name: "initialAuthModule";
        readonly type: "address";
    }, {
        readonly indexed: true;
        readonly internalType: "uint256";
        readonly name: "index";
        readonly type: "uint256";
    }];
    readonly name: "AccountCreation";
    readonly type: "event";
}, {
    readonly anonymous: false;
    readonly inputs: readonly [{
        readonly indexed: true;
        readonly internalType: "address";
        readonly name: "account";
        readonly type: "address";
    }, {
        readonly indexed: true;
        readonly internalType: "address";
        readonly name: "initialAuthModule";
        readonly type: "address";
    }];
    readonly name: "AccountCreationWithoutIndex";
    readonly type: "event";
}, {
    readonly inputs: readonly [];
    readonly name: "accountCreationCode";
    readonly outputs: readonly [{
        readonly internalType: "bytes";
        readonly name: "";
        readonly type: "bytes";
    }];
    readonly stateMutability: "pure";
    readonly type: "function";
}, {
    readonly inputs: readonly [{
        readonly internalType: "address";
        readonly name: "moduleSetupContract";
        readonly type: "address";
    }, {
        readonly internalType: "bytes";
        readonly name: "moduleSetupData";
        readonly type: "bytes";
    }];
    readonly name: "deployAccount";
    readonly outputs: readonly [{
        readonly internalType: "address";
        readonly name: "proxy";
        readonly type: "address";
    }];
    readonly stateMutability: "nonpayable";
    readonly type: "function";
}, {
    readonly inputs: readonly [{
        readonly internalType: "address";
        readonly name: "moduleSetupContract";
        readonly type: "address";
    }, {
        readonly internalType: "bytes";
        readonly name: "moduleSetupData";
        readonly type: "bytes";
    }, {
        readonly internalType: "uint256";
        readonly name: "index";
        readonly type: "uint256";
    }];
    readonly name: "deployCounterFactualAccount";
    readonly outputs: readonly [{
        readonly internalType: "address";
        readonly name: "proxy";
        readonly type: "address";
    }];
    readonly stateMutability: "nonpayable";
    readonly type: "function";
}, {
    readonly inputs: readonly [{
        readonly internalType: "address";
        readonly name: "moduleSetupContract";
        readonly type: "address";
    }, {
        readonly internalType: "bytes";
        readonly name: "moduleSetupData";
        readonly type: "bytes";
    }, {
        readonly internalType: "uint256";
        readonly name: "index";
        readonly type: "uint256";
    }];
    readonly name: "getAddressForCounterFactualAccount";
    readonly outputs: readonly [{
        readonly internalType: "address";
        readonly name: "_account";
        readonly type: "address";
    }];
    readonly stateMutability: "view";
    readonly type: "function";
}];
//# sourceMappingURL=Factory.d.ts.map