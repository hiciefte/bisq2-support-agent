export const DEFAULT_PRIVACY_RETENTION_DAYS = 30

export function getPrivacyRetentionDays(
  configuredValue: string | undefined = process.env.DATA_RETENTION_DAYS
): number {
  const normalizedValue = configuredValue?.trim()

  if (!normalizedValue || !/^\d+$/.test(normalizedValue)) {
    return DEFAULT_PRIVACY_RETENTION_DAYS
  }

  const retentionDays = Number(normalizedValue)
  if (
    !Number.isSafeInteger(retentionDays) ||
    retentionDays < 1 ||
    retentionDays > DEFAULT_PRIVACY_RETENTION_DAYS
  ) {
    return DEFAULT_PRIVACY_RETENTION_DAYS
  }

  return retentionDays
}
