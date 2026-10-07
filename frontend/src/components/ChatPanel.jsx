import { useEffect, useRef, useState } from 'react';

export default function ChatPanel({ messages, onSend, onClear, loading, error }) {
  const [text, setText] = useState('');
  const endRef = useRef(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);
  const submit = (event) => {
    event.preventDefault();
    if (text.trim() && !loading) {
      onSend(text.trim());
      setText('');
    }
  };
  return (
    <section className="chatCard">
      <div className="panelHeader">
        <div>
          <h2>AI Learning Assistant</h2>
          <p><span className="onlineDot" /> Online</p>
        </div>
        <button className="ghostBtn" onClick={onClear}>🗑️ Clear Chat</button>
      </div>
      <div className="messages">
        {messages.map((m) => (
          <div className={`messageRow ${m.role}`} key={m.id}>
            <div className="bubbleAvatar">{m.role === 'assistant' ? '🤖' : '👤'}</div>
            <div className="bubble"><pre>{m.content}</pre></div>
          </div>
        ))}
        {loading && (
          <div className="messageRow assistant">
            <div className="bubbleAvatar">🤖</div>
            <div className="bubble typing">Creating your roadmap...</div>
          </div>
        )}
        <div ref={endRef} />
      </div>
      {error && <div className="errorBox">{error}</div>}
      <form className="composer" onSubmit={submit}>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Type your message..." />
        <button disabled={loading || !text.trim()}>➤ Send</button>
      </form>
    </section>
  );
}
