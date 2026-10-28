import React, { useEffect, useRef, useState } from 'react';

export function TypingText({ text, animate = true, streaming = false }) {
  const [shown, setShown] = useState(() => animate ? '' : text);
  const shownRef = useRef(shown);
  useEffect(() => {
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    if (!animate || reduced) { shownRef.current = text; setShown(text); return; }
    const target = Array.from(text);
    let position = text.startsWith(shownRef.current) ? Array.from(shownRef.current).length : 0;
    let frame, last = performance.now(), credit = 0;
    if (!position) { shownRef.current = ''; setShown(''); }
    function tick(now) {
      const remaining = target.length - position;
      // Keep up with a live stream; drain larger final chunks without a long artificial wait.
      const speed = Math.max(90, remaining / 1.5);
      credit += Math.max(0, now - last) * speed / 1000; last = now;
      const count = Math.floor(credit);
      if (count > 0) {
        credit -= count; position = Math.min(target.length, position + count);
        shownRef.current = target.slice(0, position).join(''); setShown(shownRef.current);
      }
      if (position < target.length) frame = requestAnimationFrame(tick);
    }
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [text, animate]);
  return <p className="muted assistant-text">{shown}{streaming && <span className="typing-cursor" aria-hidden="true">▍</span>}</p>;
}
