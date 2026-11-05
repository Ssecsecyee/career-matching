import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

function safeLink(value) {
  try { const url=new URL(value); return url.protocol==='https:' && !url.username && !url.password ? url.href : undefined; }
  catch { return undefined; }
}

export function MarkdownAnswer({ text, pending=false }) {
  const visible=pending ? text.replace(/\[([^\]\n]+)\]\([^\)\n]*$/, '$1 (링크 작성 중)') : text;
  return <div className="markdown-answer"><ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml
    disallowedElements={['img']} urlTransform={safeLink}
    components={{
      a: ({href,children})=>{
        const safe=safeLink(href);
        if(!safe)return <span>{children}</span>;
        const host=new URL(safe).hostname;
        const label=typeof children==='string' && /^https?:\/\//i.test(children) ?
          (host==='www.work24.go.kr' || host==='work24.go.kr' ? '고용24 상세 보기' : host.endsWith('.saramin.co.kr') ? '채용공고 원문 보기' : host) : children;
        return <a className="answer-link" href={safe} target="_blank" rel="noopener noreferrer" title={safe}>{label}<span aria-hidden="true"> ↗</span></a>;
      },
      table: ({children})=><div className="answer-table"><table>{children}</table></div>,
      h1: ({children})=><h2>{children}</h2>
    }}>{visible}</ReactMarkdown></div>;
}
