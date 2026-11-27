// auto = dùng hết chỗ trống của ảnh để lặp lại nội dung: bền hơn nhưng đụng tới nhiều khối hơn,
// nên dễ bị công cụ phân tích phát hiện hơn.
export const PRESETS = [
  { id: "light", name: "Nhẹ", desc: "Khó phát hiện nhất, chứa được nhiều nhất. Chỉ nên chia sẻ dạng PNG.", redundancy: 1, delta: 5, auto: false },
  { id: "balanced", name: "Cân bằng (mặc định)", desc: "Mắt thường không thấy, chịu được nén nhẹ.", redundancy: 5, delta: 5, auto: false },
  { id: "robust", name: "Bền vững", desc: "Chịu nén và chỉnh sửa thông thường.", redundancy: 5, delta: 16, auto: false },
] as const;

export const DEFAULT_PRESET = PRESETS[1];

export type PresetId = (typeof PRESETS)[number]["id"] | "custom";

/** Dưới mức này nhiễu có thể thấy bằng mắt và ảnh dễ bị phát hiện là có giấu tin. */
export const PSNR_WARN = 38;
