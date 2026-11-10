"use client";

import React, { ComponentPropsWithoutRef, ElementType } from "react";
import { motion, Transition } from "framer-motion";

export interface TextShimmerWaveProps extends ComponentPropsWithoutRef<"p"> {
  children: string;
  as?: ElementType;
  className?: string;
  duration?: number;
  zDistance?: number;
  xDistance?: number;
  yDistance?: number;
  spread?: number;
  scale?: number;
  rotate?: number;
  baseColor?: string;
  shimmerColor?: string;
  transition?: Transition;
}

export function TextShimmerWave({
  children,
  as: Component = "p",
  className = "",
  duration = 1.2,
  zDistance = 10,
  xDistance = 0,
  yDistance = -2,
  spread = 1,
  scale = 1.1,
  rotate = 0,
  baseColor = "#64748b",
  shimmerColor = "#2563eb",
  transition,
  ...props
}: TextShimmerWaveProps) {
  const characters = children.split("");

  return (
    <Component
      className={`inline-flex flex-wrap items-center select-none ${className}`}
      {...props}
    >
      {characters.map((char, index) => {
        const delay = (index * duration) / (characters.length * spread);

        return (
          <motion.span
            key={index}
            className="inline-block"
            initial={{
              color: baseColor,
              y: 0,
              x: 0,
              scale: 1,
              rotate: 0,
            }}
            animate={{
              color: [baseColor, shimmerColor, baseColor],
              y: [0, yDistance, 0],
              x: [0, xDistance, 0],
              scale: [1, scale, 1],
              rotate: [0, rotate, 0],
            }}
            transition={{
              duration,
              repeat: Infinity,
              repeatType: "loop",
              ease: "easeInOut",
              delay,
              ...transition,
            }}
          >
            {char === " " ? "\u00A0" : char}
          </motion.span>
        );
      })}
    </Component>
  );
}

export function TextShimmerWaveColor() {
  return (
    <div className="flex flex-col items-center gap-3 text-sm font-medium">
      <TextShimmerWave baseColor="#64748b" shimmerColor="#2563eb">
        Reading message
      </TextShimmerWave>
      <TextShimmerWave baseColor="#64748b" shimmerColor="#16a34a">
        Drafting reply
      </TextShimmerWave>
      <TextShimmerWave baseColor="#64748b" shimmerColor="#e11d48">
        Retrying answer
      </TextShimmerWave>
    </div>
  );
}

export default TextShimmerWave;
