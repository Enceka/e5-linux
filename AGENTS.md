# Hardware and modem fixes

- Use each model's stock Android firmware behavior as the reference for power,
  charging, battery accounting, radio initialization and reconnection.
- Prefer the actual device's driver/RIL binary and device tree over a merely
  similar vendor source tree. Record firmware versions and the evidence used.
- Separate confirmed defects, hypotheses and untested hardware behavior in
  reports. AOSP explains the framework design; its default timers are not proof
  of the model's carrier or vendor configuration.
- Do not hide a symptom with arbitrary percentage caps, forced recalibration,
  radio resets, disabled sleep or reduced functionality. Preserve existing AT
  ownership, command ordering, boot replay and explicit user choices.
- Apply shared fixes to shared build/update paths. Keep charger-chip and board
  differences in the model profiles, and do not call an offline test a successful
  hardware validation.
