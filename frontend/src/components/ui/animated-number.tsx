"use client";

import { useSpring, useTransform, motion } from "framer-motion";
import { useEffect } from "react";

export function AnimatedNumber({
  value,
  format,
  className,
}: {
  value: number;
  format?: (n: number) => string;
  className?: string;
}) {
  const spring = useSpring(0, { bounce: 0, duration: 600 });
  const display = useTransform(spring, (v) =>
    format ? format(v) : Math.round(v).toLocaleString(),
  );

  useEffect(() => {
    spring.set(value);
  }, [spring, value]);

  return <motion.span className={className}>{display}</motion.span>;
}
