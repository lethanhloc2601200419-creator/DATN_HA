import { type Address, type Chain } from "viem";
import type { UserOperationFeeOptions } from "../types";
/**
 * Utility method returning the entry point contrafct address given a {@link Chain} object
 *
 * @param chain - a {@link Chain} object
 * @returns a {@link abi.Address} for the given chain
 * @throws if the chain doesn't have an address currently deployed
 */
export declare const getDefaultEntryPointAddress: (chain: Chain) => Address;
/**
 * Utility method returning the default simple account factory address given a {@link Chain} object
 *
 * @param chain - a {@link Chain} object
 * @returns a {@link abi.Address} for the given chain
 * @throws if the chain doesn't have an address currently deployed
 */
export declare const getDefaultSimpleAccountFactoryAddress: (chain: Chain) => Address;
export declare const minPriorityFeePerBidDefaults: Map<number, bigint>;
export declare const getDefaultUserOperationFeeOptions: (chain: Chain) => UserOperationFeeOptions;
//# sourceMappingURL=defaults.d.ts.map