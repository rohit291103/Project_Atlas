/* The spotlight overlay: dim everything, cut a hole around one element, explain
 * it, move on.
 *
 * Three things here are not decoration, and each one is a bug this went through:
 *
 * 1. **It waits for the anchor rather than assuming it.** Every screen in this
 *    app replays the whole event log, so a route change is followed by two to
 *    four seconds of skeletons. A tour that measured the element the instant it
 *    navigated would spotlight empty space. It polls for the anchor and shows
 *    the card only once there is something to point at.
 * 2. **A missing anchor skips the step.** The tour runs on any product, and
 *    plenty of them have no conflict to show or no description written yet.
 *    Waiting forever, or pointing at the top-left corner, are both worse than
 *    moving on.
 * 3. **The hole is a real hole.** The spotlight has `pointer-events: none`, so
 *    the highlighted control is still clickable — clicking it advances the tour
 *    exactly as Next does. Being shown a button you cannot press is a strange
 *    way to learn an interface.
 *
 * Hand-rolled for the same reason `router.ts` is: this is one overlay, one
 * card and a rectangle, and a tour library is a dependency, a theme to fight
 * and a second set of z-index rules.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { Route } from "../router";
import { href } from "../router";
import type { TourStep } from "../tour";

/** How long to wait for a step's anchor before giving up and skipping it.
 *  Generous, because a cold review screen against remote Supabase takes ~4s. */
const ANCHOR_TIMEOUT_MS = 12000;
const POLL_MS = 120;
/** Breathing room between the cut-out and the element inside it. */
const PAD = 8;
const CARD_W = 340;

type Rect = { top: number; left: number; width: number; height: number };

export function Tour({
  steps,
  route,
  navigate,
  onClose,
}: {
  steps: TourStep[];
  route: Route;
  navigate: (route: Route, replace?: boolean) => void;
  onClose: () => void;
}) {
  const [index, setIndex] = useState(0);
  const [rect, setRect] = useState<Rect | null>(null);
  const step = steps[index];
  // `route` is read inside an effect that must not re-run on every navigation
  // (it would restart the anchor hunt); a ref keeps it current without that.
  const routeRef = useRef(route);
  routeRef.current = route;

  /* The anchor hunt must key on *what* the step points at, never on the step
     object: `tourSteps()` returns fresh objects every render, so an effect
     depending on `step` restarted the hunt (and blanked the spotlight) on every
     parent re-render — and the parent re-renders whenever the rail refreshes. */
  const stepKey = step ? `${step.id}|${step.anchor}|${href(step.route)}` : "";
  /* The hunt also re-runs when the route changes *under* a step — which happens
     when the reviewer clicks the highlighted link instead of pressing Next.
     Without this the spotlight kept the rectangle it measured on the previous
     screen and hung there over the new one until the step advanced. */
  const routeKey = href(route);

  const finish = useCallback(() => onClose(), [onClose]);
  const next = useCallback(
    () => setIndex((i) => (i + 1 >= steps.length ? (finish(), i) : i + 1)),
    [steps.length, finish],
  );
  const back = useCallback(() => setIndex((i) => Math.max(0, i - 1)), []);

  // Navigate to the step's screen, then hunt for its anchor.
  const stepRef = useRef(step);
  stepRef.current = step;
  useEffect(() => {
    const current = stepRef.current;
    if (!current) return;
    let cancelled = false;
    setRect(null);

    const anchor = current.anchor;
    if (href(routeRef.current) !== href(current.route)) navigate(current.route);

    const started = Date.now();
    const tick = () => {
      if (cancelled) return;
      const element = document.querySelector<HTMLElement>(`[data-tour="${anchor}"]`);
      if (element) {
        element.scrollIntoView({ block: "center", behavior: "smooth" });
        // One frame after the scroll so the measurement is of where it landed.
        window.setTimeout(() => {
          if (cancelled) return;
          const box = element.getBoundingClientRect();
          setRect({ top: box.top, left: box.left, width: box.width, height: box.height });
        }, 260);
        return;
      }
      if (Date.now() - started > ANCHOR_TIMEOUT_MS) {
        // Nothing to point at on this product — move on rather than stall.
        setIndex((i) => (i + 1 >= steps.length ? (finish(), i) : i + 1));
        return;
      }
      window.setTimeout(tick, POLL_MS);
    };
    tick();
    return () => {
      cancelled = true;
    };
  }, [stepKey, routeKey, navigate, steps.length, finish]);

  // Keep the hole over the element while the page moves under it.
  useEffect(() => {
    if (!step || !rect) return;
    const remeasure = () => {
      const element = document.querySelector<HTMLElement>(`[data-tour="${step.anchor}"]`);
      if (!element) return;
      const box = element.getBoundingClientRect();
      setRect({ top: box.top, left: box.left, width: box.width, height: box.height });
    };
    window.addEventListener("resize", remeasure);
    window.addEventListener("scroll", remeasure, true);
    return () => {
      window.removeEventListener("resize", remeasure);
      window.removeEventListener("scroll", remeasure, true);
    };
  }, [step, rect]);

  // Clicking the highlighted thing is the same as pressing Next — the tour
  // says "click that", so clicking that has to work.
  useEffect(() => {
    if (!step || !rect) return;
    const element = document.querySelector<HTMLElement>(`[data-tour="${step.anchor}"]`);
    if (!element) return;
    const onClick = () => window.setTimeout(next, 350);
    element.addEventListener("click", onClick);
    return () => element.removeEventListener("click", onClick);
  }, [step, rect, next]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") finish();
      if (event.key === "ArrowRight" || event.key === "Enter") next();
      if (event.key === "ArrowLeft") back();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [next, back, finish]);

  if (!step) return null;

  return (
    <div className="tour" role="dialog" aria-modal="false" aria-label="Guided tour">
      {rect ? (
        <>
          <div
            className="tour__hole"
            style={{
              top: rect.top - PAD,
              left: rect.left - PAD,
              width: rect.width + PAD * 2,
              height: rect.height + PAD * 2,
            }}
          />
          <TourCard
            step={step}
            rect={rect}
            index={index}
            total={steps.length}
            onNext={next}
            onBack={back}
            onClose={finish}
          />
        </>
      ) : (
        // Between screens: dim everything and say why nothing is highlighted
        // yet, rather than flashing a card at the wrong element.
        <div className="tour__waiting">
          <span className="tour__spinner" aria-hidden />
          Loading that screen…
        </div>
      )}
    </div>
  );
}

function TourCard({
  step,
  rect,
  index,
  total,
  onNext,
  onBack,
  onClose,
}: {
  step: TourStep;
  rect: Rect;
  index: number;
  total: number;
  onNext: () => void;
  onBack: () => void;
  onClose: () => void;
}) {
  const place = step.place ?? "bottom";
  const gap = 18;
  const style: React.CSSProperties = { width: CARD_W };

  // Preferred side, then clamped into the viewport. A card half off-screen is
  // the most common failure of hand-rolled coach marks.
  if (place === "right") style.left = rect.left + rect.width + gap;
  else if (place === "left") style.left = rect.left - CARD_W - gap;
  else style.left = rect.left + rect.width / 2 - CARD_W / 2;

  if (place === "bottom") style.top = rect.top + rect.height + gap;
  else if (place === "top") style.top = rect.top - gap;
  else style.top = rect.top;

  style.left = Math.min(Math.max(12, Number(style.left)), window.innerWidth - CARD_W - 12);
  style.top = Math.min(Math.max(12, Number(style.top)), window.innerHeight - 210);
  if (place === "top") style.transform = "translateY(-100%)";

  return (
    <div className="tour__card" style={style}>
      <div className="tour__step">
        {index + 1} of {total}
      </div>
      <h2 className="tour__title">{step.title}</h2>
      <p className="tour__body">{step.body}</p>
      <div className="tour__row">
        <button type="button" className="action action--primary" onClick={onNext}>
          {index + 1 === total ? "Done" : "Next"}
        </button>
        {index > 0 && (
          <button type="button" className="action" onClick={onBack}>
            Back
          </button>
        )}
        <button type="button" className="link-button tour__skip" onClick={onClose}>
          Skip
        </button>
      </div>
    </div>
  );
}
