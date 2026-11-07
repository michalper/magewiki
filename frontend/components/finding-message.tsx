// Several quality-finding messages (CVE/advisory checks) end with a
// "(https://...)" citation — rendered as a real link instead of dead text.
const TRAILING_URL = /^([\s\S]*)\((https?:\/\/[^\s)]+)\)$/;

export function FindingMessage({ message }: { message: string }) {
  const match = message.match(TRAILING_URL);
  if (!match) {
    return <>{message}</>;
  }
  const [, text, url] = match;
  return (
    <>
      {text}(
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="text-primary hover:underline break-all"
      >
        {url}
      </a>
      )
    </>
  );
}
