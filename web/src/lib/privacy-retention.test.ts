import {
  DEFAULT_PRIVACY_RETENTION_DAYS,
  getPrivacyRetentionDays,
} from "./privacy-retention"

describe("getPrivacyRetentionDays", () => {
  const originalRetentionDays = process.env.DATA_RETENTION_DAYS

  afterEach(() => {
    if (originalRetentionDays === undefined) {
      delete process.env.DATA_RETENTION_DAYS
    } else {
      process.env.DATA_RETENTION_DAYS = originalRetentionDays
    }
  })

  it("reads the retention window at server runtime", () => {
    process.env.DATA_RETENTION_DAYS = "14"

    expect(getPrivacyRetentionDays()).toBe(14)
  })

  it("accepts positive integer values with surrounding whitespace", () => {
    expect(getPrivacyRetentionDays(" 7 ")).toBe(7)
    expect(getPrivacyRetentionDays("0030")).toBe(30)
  })

  it.each(["", "0", "-1", "1.5", "31", "thirty", "999999999999999999999999"])(
    "uses the default for an invalid value of %p",
    (configuredValue) => {
      expect(getPrivacyRetentionDays(configuredValue)).toBe(
        DEFAULT_PRIVACY_RETENTION_DAYS
      )
    }
  )

  it("defaults to 30 days when the environment value is absent", () => {
    delete process.env.DATA_RETENTION_DAYS

    expect(getPrivacyRetentionDays()).toBe(30)
  })
})
