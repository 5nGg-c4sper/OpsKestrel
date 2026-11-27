import type { PropsWithChildren, ReactNode } from "react";
import { className } from "../lib/format";

interface SurfaceProps extends PropsWithChildren {
  className?: string;
  header?: ReactNode;
  footer?: ReactNode;
}

export function Surface({
  children,
  className: extraClassName,
  header,
  footer
}: SurfaceProps) {
  return (
    <section className={className("surface", extraClassName)}>
      {header ? <div className="surface-header">{header}</div> : null}
      <div className="surface-body">{children}</div>
      {footer ? <div className="surface-footer">{footer}</div> : null}
    </section>
  );
}
