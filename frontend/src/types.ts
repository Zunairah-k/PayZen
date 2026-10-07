export type Status = "Verified" | "Likely match" | "Contradicted" | "Not found" | "Duplicate" | "Can't verify yet";

export interface Claim {
  claim_id: string;
  source_file?: string | null;
  payer_name?: string | null;
  payee_name?: string | null;
  amount?: number | null;
  timestamp?: string | null;
  reference?: string | null;
  status_shown?: string | null;
  confidence?: Record<string, number>;
  extraction_notes?: string | null;
}
export interface StatementRow {
  row_id: string;
  datetime?: string | null;
  narration?: string | null;
  debit?: number | null;
  credit?: number | null;
  balance?: number | null;
  extracted_reference?: string | null;
  name_hint?: string | null;
}
export interface StatementMeta {
  coverage_start?: string | null;
  coverage_end?: string | null;
  mapping_used?: Record<string, string>;
  balance_chain_result?: string | null;
  parse_confidence?: number;
  row_count?: number;
  warnings?: string[];
}
export interface Verdict {
  claim_id: string;
  status: Status;
  tier?: number | null;
  matched_row_id?: string | null;
  confidence: number;
  reasons: string[];
  field_differences: Record<string, string>;
  follow_up_after?: string | null;
  suggested_reply?: string | null;
}