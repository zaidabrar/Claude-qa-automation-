/** Normalise Indian mobile numbers to +91XXXXXXXXXX. Returns null for anything that isn't a valid mobile. */
export function normalizeIndianMobile(input: string): string | null {
  const digits = input.replace(/[\s\-()]/g, "").replace(/^\+?91(?=\d{10}$)/, "").replace(/^0(?=\d{10}$)/, "");
  return /^[6-9]\d{9}$/.test(digits) ? `+91${digits}` : null;
}

export function maskPhone(phone: string): string {
  return phone.replace(/^(\+91)(\d{2})\d{6}(\d{2})$/, "$1 $2xxxxxx$3");
}
