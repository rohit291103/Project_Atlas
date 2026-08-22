/* What a product or a feature *is*, in the PM's own words.
 *
 * Slice 4 of `docs/decisions/2026-08-19-product-orientation-rerun-safety-and-
 * demo-data.md`, and it amends the 2026-08-16 Overview decision rather than
 * reversing it. That decision replaced a title-and-a-sentence with counts and a
 * meter, and it was right *for the returning reviewer* — "how much is mine to
 * do?" is the question they ask first. What it got wrong was treating the two as
 * either/or: it removed the only orientation a first-time visitor had. So this
 * sits **above** the counts, and the counts stay exactly as they were.
 *
 * One component for both layers because the behaviour is identical and the
 * layering is the point — product → feature → claims → source thread, with
 * something to read at every level rather than only the bottom two.
 *
 * The text is authored, never extracted. That is not a UI detail: an extracted
 * summary would be a *claim about the product*, and a claim starts unconfirmed
 * and carries provenance. Nothing here does, which is why it renders as plain
 * prose with no source strip and no confirm control — it is not part of the
 * draft under review.
 */

import { useEffect, useRef, useState } from "react";
import { ApiError } from "../api";

/** Matches `DESCRIPTION_MAX_LENGTH` in `models/schema.py`. Stated here so the
 * textarea stops you at the same place the API would 422 you. */
const MAX_LENGTH = 2000;

export function Orientation({
  description,
  writable,
  what,
  placeholder,
  onSave,
}: {
  description: string | null;
  writable: boolean;
  /** The noun used in the empty-state prompt: "product" or "feature". */
  what: string;
  placeholder: string;
  onSave: (description: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(description ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const field = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (editing) field.current?.focus();
  }, [editing]);

  const open = () => {
    setDraft(description ?? "");
    setError(null);
    setEditing(true);
  };

  const save = async () => {
    setSaving(true);
    try {
      await onSave(draft.trim());
      setEditing(false);
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Couldn't save that.");
    } finally {
      setSaving(false);
    }
  };

  if (editing) {
    return (
      <div className="orient orient--editing">
        <textarea
          ref={field}
          className="orient__field"
          rows={3}
          maxLength={MAX_LENGTH}
          value={draft}
          placeholder={placeholder}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            /* ⌘/Ctrl+Enter saves; plain Enter inserts a newline, because this is
               prose and a paragraph break is a normal thing to want. */
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) void save();
            if (event.key === "Escape") setEditing(false);
          }}
        />
        <div className="orient__row">
          <button
            type="button"
            className="action action--primary"
            onClick={() => void save()}
            disabled={saving}
          >
            {saving ? "Saving…" : "Save"}
          </button>
          <button type="button" className="action" onClick={() => setEditing(false)}>
            Cancel
          </button>
          {/* Blank clears, and saying so is the difference between an empty box
              that looks broken and one that is an instruction. */}
          <span className="orient__hint">
            {draft.trim() ? "⌘↵ to save" : "Save an empty box to remove the description"}
          </span>
          {error && <span className="orient__error">{error}</span>}
        </div>
      </div>
    );
  }

  if (!description) {
    /* Nothing written, and nothing you could do about it: say nothing at all
       rather than showing a reader a permanently empty slot. */
    if (!writable) return null;
    return (
      <p className="orient orient--empty">
        <button type="button" className="link-button" onClick={open}>
          + Say what this {what} is
        </button>
      </p>
    );
  }

  return (
    <p className="orient">
      <span className="orient__text">{description}</span>
      {writable && (
        <button type="button" className="orient__edit link-button" onClick={open}>
          Edit
        </button>
      )}
    </p>
  );
}
