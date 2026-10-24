import { z } from "zod";
import type { PriceBreakdown } from "./pricing";

// Kept apart from pricing.ts so client components can use the price maths without bundling zod.
export const priceBreakdownSchema = z.object({
  exShowroom: z.number().int().positive(),
  rto: z.number().int().min(0),
  insurance: z.number().int().min(0),
  accessories: z.number().int().min(0),
  extendedWarranty: z.number().int().min(0).default(0),
  otherCharges: z.number().int().min(0).default(0),
  discount: z.number().int().min(0).default(0),
}) satisfies z.ZodType<PriceBreakdown>;
