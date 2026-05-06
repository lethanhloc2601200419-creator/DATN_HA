import { type Chain } from "viem";
import { z } from "zod";
export declare const ChainSchema: z.ZodType<Chain, z.ZodTypeDef, Chain>;
export declare const HexSchema: z.ZodType<`0x${string}`, z.ZodTypeDef, `0x${string}`>;
export declare const BigNumberishSchema: z.ZodUnion<[z.ZodType<`0x${string}`, z.ZodTypeDef, `0x${string}`>, z.ZodNumber, z.ZodBigInt]>;
export declare const BigNumberishRangeSchema: z.ZodObject<{
    min: z.ZodOptional<z.ZodUnion<[z.ZodType<`0x${string}`, z.ZodTypeDef, `0x${string}`>, z.ZodNumber, z.ZodBigInt]>>;
    max: z.ZodOptional<z.ZodUnion<[z.ZodType<`0x${string}`, z.ZodTypeDef, `0x${string}`>, z.ZodNumber, z.ZodBigInt]>>;
}, "strict", z.ZodTypeAny, {
    min?: number | bigint | `0x${string}` | undefined;
    max?: number | bigint | `0x${string}` | undefined;
}, {
    min?: number | bigint | `0x${string}` | undefined;
    max?: number | bigint | `0x${string}` | undefined;
}>;
export declare const PercentageSchema: z.ZodObject<{
    percentage: z.ZodNumber;
}, "strict", z.ZodTypeAny, {
    percentage: number;
}, {
    percentage: number;
}>;
