'use client';

/* The machine's sentence, kept and kept out of the way.
 *
 * `fault.message` is written for whoever has to fix the deployment: it names
 * the environment variable, the path, the exception. That is worth keeping —
 * a refusal a reader cannot trace is a refusal they have to take on faith —
 * but it is English prose in a Persian interface, and printing it beside the
 * explanation makes it look like the explanation.
 *
 * So the visible text of every screen is Persian, and this is one click away
 * under a Persian label. The rule it enforces: `fault.fa` is what the page
 * SAYS, `fault.message` is what an operator can OPEN. A page that shows only
 * the second is telling a buyer to read a stack trace; one that shows neither
 * is asking to be trusted.
 *
 * `break-all` because the payload is often a path or a quoted id with no
 * spaces to wrap at, and it must not push the panel wider than the screen.
 */
export default function TechDetail({ message }: { message: string }) {
  if (!message) return null;
  return (
    <details className="mt-3 group">
      <summary
        className="cursor-pointer list-none text-[11.5px] text-ink-3
                   hover:text-ink-2 select-none"
      >
        <span className="inline-block transition-transform
                         group-open:rotate-90">‹</span>{' '}
        جزئیات فنی
      </summary>
      <p
        className="m-0 mt-2 num text-[11.5px] text-ink-3 leading-6
                   whitespace-pre-wrap break-all bg-bad-soft/40 border
                   border-line rounded-[2px] px-2.5 py-2"
        dir="ltr"
      >
        {message}
      </p>
    </details>
  );
}
