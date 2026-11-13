export const PRESETS = [
  { id: "capacity", name: "Dung lượng cao", desc: "Giấu được nhiều nhất, chịu nén nhẹ.", redundancy: 1, delta: 12 },
  { id: "balanced", name: "Cân bằng", desc: "Khuyên dùng cho đa số trường hợp.", redundancy: 5, delta: 16 },
  { id: "robust", name: "Bền vững", desc: "Chịu nén JPEG, cắt mép, nhiễu tốt hơn.", redundancy: 15, delta: 24 },
] as const;

export type PresetId = (typeof PRESETS)[number]["id"] | "custom";
