"use client";

import { useChat } from "@ai-sdk/react";

export default function Chat() {
  const { messages, input, handleInputChange, handleSubmit } = useChat({
    body: { userId: "demo-user" },
  });

  return (
    <main style={{ maxWidth: 640, margin: "0 auto", padding: 24 }}>
      <h1>AcmeSync Support</h1>
      {messages.map((m) => (
        <p key={m.id}>
          <b>{m.role === "user" ? "You" : "Assistant"}:</b> {m.content}
        </p>
      ))}
      <form onSubmit={handleSubmit}>
        <input
          value={input}
          onChange={handleInputChange}
          placeholder="Ask about AcmeSync..."
          style={{ width: "100%", padding: 8 }}
        />
      </form>
    </main>
  );
}
