import type { Status } from "./types";

export const STATUS_ORDER: Status[] = ["Verified", "Likely match", "Contradicted", "Not found", "Duplicate", "Can't verify yet"];

export const STATUS_COLORS: Record<Status, string> = {
  "Verified": "#1f8a4c",
  "Likely match": "#1f7a8c",
  "Contradicted": "#d9822b",
  "Not found": "#c0392b",
  "Duplicate": "#7b4fb3",
  "Can't verify yet": "#6b7a90",
};