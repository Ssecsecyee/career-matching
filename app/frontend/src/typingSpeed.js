// Characters per second: readable for short chunks, bounded catch-up for long replies.
export function typingSpeed(remaining) {
  return remaining > 600 ? 90 : remaining > 240 ? 60 : 36;
}
