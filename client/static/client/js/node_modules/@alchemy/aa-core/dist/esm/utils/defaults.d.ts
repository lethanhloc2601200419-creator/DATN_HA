import { type Address, type Chain } from "viem";
import type { UserOperationFeeOptions } from "../types";
export declare const getDefaultEntryPointAddress: (chain: Chain) => Address;
export declare const getDefaultSimpleAccountFactoryAddress: (chain: Chain) => Address;
export declare const minPriorityFeePerBidDefaults: Map<number, bigint>;
export declare const getDefaultUserOperationFeeOptions: (chain: Chain) => UserOperationFeeOptions;
