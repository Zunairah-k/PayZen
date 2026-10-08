import { useRef, useState } from "react";

const keyOf = (f: File) => `${f.name}:${f.size}:${f.lastModified}`;

function merge(existing: File[], added: File[]) {
  const seen = new Set(existing.map(keyOf));
  return [...existing, ...added.filter((f) => !seen.has(keyOf(f)))];
}

interface DropZoneProps {
  title: string;
  hint: string;
  accept: string;
  multiple: boolean;
  files: File[];
  onFiles: (f: File[]) => void;
  onRemove?: (index: number) => void;
  onClear?: () => void;
}

function DropZone({ title, hint, accept, multiple, files, onFiles, onRemove, onClear }: DropZoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const shown = files.slice(0, 6);
  return (
    <div
      className={`dropzone ${over ? "over" : ""}`}
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        const list = Array.from(e.dataTransfer.files);
        if (list.length) onFiles(multiple ? list : [list[0]]);
      }}
    >
      <input
        ref={inputRef}
        type="file"
        hidden
        accept={accept}
        multiple={multiple}
        onChange={(e) => {
          const list = Array.from(e.target.files ?? []);
          if (list.length) onFiles(multiple ? list : [list[0]]);
          e.target.value = "";
        }}
      />
      <strong>{title}</strong>
      <span>{hint}</span>
      {files.length > 0 && (
        <em>
          {files.length} file{files.length > 1 ? "s" : ""} selected
          {files.length === 1 ? `: ${files[0].name}` : ""}
        </em>
      )}
      {multiple && files.length > 1 && (
        <ul className="file-list" onClick={(e) => e.stopPropagation()}>
          {shown.map((f, i) => (
            <li key={keyOf(f)}>
              {f.name}
              {onRemove && <button type="button" onClick={() => onRemove(i)} aria-label={`Remove ${f.name}`}>×</button>}
            </li>
          ))}
          {files.length > shown.length && <li>+{files.length - shown.length} more</li>}
        </ul>
      )}
      {multiple && files.length > 0 && onClear && (
        <button type="button" className="clear-files" onClick={(e) => { e.stopPropagation(); onClear(); }}>
          Clear all
        </button>
      )}
    </div>
  );
}

interface Props {
  claimFiles: File[];
  statementFile: File | null;
  onClaimFiles: (f: File[]) => void;
  onStatementFile: (f: File) => void;
}

export default function UploadPanel({ claimFiles, statementFile, onClaimFiles, onStatementFile }: Props) {
  return (
    <div className="upload-panel">
      <DropZone
        title="1. Payment screenshots"
        hint="Drop or click to add the screenshots people sent you (you can add more than once)"
        accept="image/*"
        multiple
        files={claimFiles}
        onFiles={(added) => onClaimFiles(merge(claimFiles, added))}
        onRemove={(i) => onClaimFiles(claimFiles.filter((_, idx) => idx !== i))}
        onClear={() => onClaimFiles([])}
      />
      <DropZone
        title="2. Your bank statement"
        hint="CSV, XLSX, PDF, text or a photo. Any format."
        accept=".csv,.xlsx,.xls,.pdf,.txt,image/*"
        multiple={false}
        files={statementFile ? [statementFile] : []}
        onFiles={(f) => onStatementFile(f[0])}
      />
    </div>
  );
}