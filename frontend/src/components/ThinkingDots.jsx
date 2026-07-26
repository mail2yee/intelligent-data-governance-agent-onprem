// Animated "thinking..." indicator shown while /api/chat is streaming.
export default function ThinkingDots({ label }) {
  return (
    <>
      {label}
      <span className="thinking-indicator">
        <span className="dot"></span>
        <span className="dot"></span>
        <span className="dot"></span>
      </span>
    </>
  )
}
