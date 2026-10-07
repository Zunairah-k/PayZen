import { useRef, useState } from "react";

interface DropZoneProps {
  title: string;
  hint: string;
  accept: string;
  multiple: boolean;
  files: File[];
  onFiles: (f: File[]) => void;
}

function DropZone({ title, hint, accept, multiple, files, onFiles }: DropZoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
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
          if (list.length) onFiles(list);
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
        hint="Drop or click to add the screenshots people sent you"
        accept="image/*"
        multiple
        files={claimFiles}
        onFiles={onClaimFiles}
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