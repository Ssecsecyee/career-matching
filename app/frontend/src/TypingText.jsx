import React, { useEffect, useRef, useState } from 'react';
import { typingSpeed } from './typingSpeed.js';

export function TypingText({ text, animate = true, streaming = false }) {
  const [shown, setShown] = useState(() => animate ? '' : text);
  const [revealAll, setRevealAll] = useState(false);
  const shownRef = useRef(shown);
  useEffect(() => {
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    if (!animate || reduced || revealAll) { shownRef.current = text; setShown(text); return; }
    const target = Array.from(text);
    let position = text.startsWith(shownRef.current) ? Array.from(shownRef.current).length : 0;
    let frame, last = performance.now(), credit = 0;
    if (!position) { shownRef.current = ''; setShown(''); }
    function tick(now) {
      credit += Math.min(100, Math.max(0, now - last)) * typingSpeed(target.length - position) / 1000;
      last = now;
      const count = Math.floor(credit);
      if (count > 0) {
        credit -= count; position = Math.min(target.length, position + count);
        shownRef.current = target.slice(0, position).join(''); setShown(shownRef.current);
      }
      if (position < target.length) frame = requestAnimationFrame(tick);
    }
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [text, animate, revealAll]);
  const typing = animate && !revealAll && shown !== text;
  return <div className="typing-answer">
    {(streaming || typing) && <div className="typing-status"><span role="status">{streaming ? '답변 작성 중' : '답변 표시 중'}</span>{typing && <button className="quiet" type="button" onClick={() => setRevealAll(true)}>전체 보기</button>}</div>}
    <p className="muted assistant-text">{shown}{(streaming || typing) && <span className="typing-cursor" aria-hidden="true">▍</span>}</p>
  </div>;
}
