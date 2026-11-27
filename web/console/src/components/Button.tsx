import type { ButtonHTMLAttributes, ReactNode } from "react";
import { className } from "../lib/format";

type ButtonVariant = "primary" | "secondary" | "quiet" | "danger";
type ButtonSize = "default" | "compact";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: ReactNode;
}

export function Button({
  children,
  className: extraClassName,
  variant = "secondary",
  size = "default",
  icon,
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button
      {...props}
      type={type}
      className={className(
        "button",
        `button-${variant}`,
        `button-${size}`,
        extraClassName
      )}
    >
      {icon}
      {children}
    </button>
  );
}
