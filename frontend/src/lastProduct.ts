/* Which product the reviewer was last inside.
 *
 * A PM owns one product, sometimes two — Google Meet and Google Keep, say —
 * and those are two different jobs, not two rows of one list. So a product is
 * a context you are *inside*, and the only sensible thing to reopen on the
 * next sign-in is the context you left. Asking "which product today?" every
 * morning is a question the app can almost always answer itself.
 *
 * Deliberately localStorage and not the session cookie: this is a per-browser
 * convenience, not a fact about identity, and it must never be something the
 * client can use to influence what the server shows it. The workspace is the
 * server's business; which product you were reading is yours.
 *
 * A remembered id is always re-checked against the products that actually came
 * back — products get deleted, and a dangling id must degrade to "choose one"
 * rather than to a blank screen pointed at something gone.
 */

const KEY = "atlas.lastProduct";

export function readLastProduct(): string | null {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    // Private-mode Safari throws on localStorage. Forgetting the last product
    // is a downgrade, not a failure — never let it take the app down with it.
    return null;
  }
}

export function rememberProduct(productId: string): void {
  try {
    window.localStorage.setItem(KEY, productId);
  } catch {
    /* see above */
  }
}

/** Where to land someone who has just signed in.
 *
 * The remembered product wins, then the only product if there is exactly one,
 * and otherwise nothing — with two or more products and no history, guessing
 * would drop the PM into the wrong job half the time, and the product list is
 * the honest answer.
 */
export function landingProductId(available: readonly { id: string }[]): string | null {
  const remembered = readLastProduct();
  if (remembered && available.some((product) => product.id === remembered)) return remembered;
  if (available.length === 1) return available[0]!.id;
  return null;
}
