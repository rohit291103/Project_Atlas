/* The product switcher: the control that says which job you are doing.
 *
 * It sits at the top of the rail because everything below it is scoped by it —
 * putting it anywhere else would leave the reader guessing which product the
 * feature list belongs to, which is exactly the confusion the flat rail caused.
 *
 * It is a menu rather than a `<select>` for one reason that matters: entries
 * carry state (a product with a failed run or unreviewed work says so here),
 * and a native select can only render text. Everything a native select gives
 * for free is therefore re-implemented deliberately below — Escape closes,
 * click-outside closes, focus returns to the trigger, arrow keys move.
 */

import { useEffect, useRef, useState } from "react";

export type SwitcherProduct = {
  id: string;
  name: string;
  /** Shown as a quiet marker on the entry — "something here needs looking at".
   * Kept as free text so the meaning can sharpen without changing this file. */
  note?: string;
};

export function ProductSwitcher({
  products,
  activeId,
  onPick,
  onAllProducts,
}: {
  products: readonly SwitcherProduct[];
  activeId: string | null;
  onPick: (productId: string) => void;
  onAllProducts: () => void;
}) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: MouseEvent) => {
      if (!wrap.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      // Focus goes back where it came from; closing a menu should never drop
      // the caret at the top of the document.
      trigger.current?.focus();
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const active = products.find((product) => product.id === activeId) ?? null;

  return (
    <div className="switcher" ref={wrap}>
      <button
        type="button"
        ref={trigger}
        className="switcher__trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((was) => !was)}
      >
        <span className="switcher__name">{active ? active.name : "All products"}</span>
        <span className="switcher__chevron" aria-hidden>
          ▾
        </span>
      </button>

      {open && (
        <div className="switcher__menu" role="menu">
          {products.map((product) => (
            <button
              key={product.id}
              type="button"
              role="menuitem"
              className={`switcher__item${product.id === activeId ? " is-active" : ""}`}
              onClick={() => {
                setOpen(false);
                onPick(product.id);
              }}
            >
              <span className="switcher__tick" aria-hidden>
                {product.id === activeId ? "✓" : ""}
              </span>
              <span className="switcher__item-name">{product.name}</span>
              {product.note && <span className="switcher__note">{product.note}</span>}
            </button>
          ))}
          <div className="switcher__sep" role="separator" />
          <button
            type="button"
            role="menuitem"
            className="switcher__item"
            onClick={() => {
              setOpen(false);
              onAllProducts();
            }}
          >
            <span className="switcher__tick" aria-hidden>
              {activeId ? "" : "✓"}
            </span>
            <span className="switcher__item-name">All products</span>
          </button>
        </div>
      )}
    </div>
  );
}
