import type { ReactNode } from "react";

// Plain-language explanations for the product's domain terms. The Review Surface
// is dense with analysis vocabulary (advisory rank, falsification, claim support);
// these definitions let a non-expert reader hover any term and learn what it means
// AND why it is useful, instead of guessing. Keep each one short and jargon-free.
export const GLOSSARY = {
  advisoryRank:
    "The agent's plausibility order, set after it challenged every hypothesis. It's a ranking to guide your review — not a probability, and not the confirmed root cause until a human decides.",
  generatedOrder:
    "Where this sat when the agent first drafted the list, before challenges re-ordered it. Shown so you can see when the ranking changed its mind.",
  whyThisRank:
    "The five things the agent weighed to place this hypothesis here. The ranking guides your attention; it never replaces your judgment.",
  supported:
    "Every major claim here is backed by a verified citation to your evidence.",
  partial:
    "Some claims are backed by evidence, but at least one is only partly supported. Read the caution note before relying on it.",
  unsupported:
    "At least one major claim has no verified citation. It stays visible for audit, but don't treat it as established fact.",
  assumption:
    "Stated without a supporting citation — treat it as an assumption to check, not a verified fact.",
  reviewProposed:
    "Waiting for your call. Use Accept or Reject to record your decision.",
  reviewAccepted: "You marked this hypothesis as accepted.",
  reviewRejected: "You marked this hypothesis as rejected.",
  proposedAlternative:
    "The agent's own hypotheses missed this, so its falsifier raised it as an alternative — then challenged and ranked it like any other. Not a root cause.",
  leadingChallenged:
    "Ranked first by plausibility, but an unresolved critical challenge means it can't be presented as the root cause without an explicit human override.",
  challengeCritical:
    "The agent found evidence serious enough that this can't be called the root cause without an explicit human override.",
  challengeMaterial:
    "The agent found evidence that weakens this hypothesis or limits its role. Worth weighing, but not disqualifying.",
  challengeMinor:
    "The agent raised a small caveat that only slightly weakens this hypothesis.",
  falsification:
    "The agent's attempt to disprove its own hypothesis — a built-in stress test, not a verdict against it.",
  counterclaims:
    "Specific, cited points that argue against this hypothesis.",
  evidenceGaps:
    "What's missing from the evidence that would confirm or rule this out.",
  falsificationTests:
    "Concrete checks you could run to prove or disprove this.",
  remediation:
    "Fixes the agent drafted for this cause. They're proposals — accept or reject them in the remediation panel.",
  unknowns: "Open questions the agent couldn't answer from the evidence.",
  validationSteps: "How to confirm this hypothesis before you act on it.",
} as const;

// A hover/focus tooltip. CSS-only (no positioning library): the bubble is absolutely
// positioned and revealed by the group's hover/focus-within state, so it works on
// mouse AND keyboard. The wrapper is focusable so keyboard users reach the same help.
export function Tip({
  text,
  children,
  className = "",
}: {
  text: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span className={`group/tip relative inline-flex ${className}`} tabIndex={0}>
      {children}
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-1.5 w-max max-w-[16rem] -translate-x-1/2 translate-y-1 rounded-lg bg-slate-900 px-2.5 py-1.5 text-xs font-normal normal-case leading-snug tracking-normal text-slate-50 opacity-0 shadow-lg ring-1 ring-slate-900/10 transition-all duration-150 group-hover/tip:translate-y-0 group-hover/tip:opacity-100 group-focus-within/tip:translate-y-0 group-focus-within/tip:opacity-100"
      >
        {text}
      </span>
    </span>
  );
}

// A small "?" marker that carries an explanation. Use it next to a section heading
// or label where there is no existing word to attach the tooltip to.
export function InfoTip({ text, className = "" }: { text: string; className?: string }) {
  return (
    <Tip text={text}>
      <span
        aria-label={text}
        className={`inline-flex h-3.5 w-3.5 cursor-help items-center justify-center rounded-full border border-slate-300 text-[9px] font-bold leading-none text-slate-400 transition hover:border-slate-400 hover:text-slate-600 ${className}`}
      >
        ?
      </span>
    </Tip>
  );
}
