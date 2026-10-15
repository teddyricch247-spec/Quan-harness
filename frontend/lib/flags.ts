// Phase Convert (C4, "Which tab is the default?").
//
// CHAT_ENABLED is flipped by Phase 7.1 when the Chat surface exists. Until then the Chat | Code
// switch is not rendered at all, so there is no dead tab, and `/` lands on Code. (C4 also names a
// NEXT_PUBLIC_NEW_SHELL flag for the *transition*; with every old page replaced in this same pass
// there is no old shell left to fall back to, so it isn't implemented — see the hand-off notes.)
//
// `process.env.NEXT_PUBLIC_*` has to be referenced literally for Next to inline it at build time.
export const CHAT_ENABLED = process.env.NEXT_PUBLIC_CHAT_ENABLED === "true";

/** Where `/` and the "Chat" tab go. */
export const HOME_PATH = CHAT_ENABLED ? "/ask" : "/projects";
