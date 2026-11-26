import { useEffect, useRef } from "react";
import { motion, useMotionValue, useSpring } from "framer-motion";

export default function CustomCursor() {
  const cursorX = useMotionValue(-100);
  const cursorY = useMotionValue(-100);
  const isHovering = useRef(false);

  const springCfg = { damping: 25, stiffness: 300, mass: 0.5 };
  const springX = useSpring(cursorX, springCfg);
  const springY = useSpring(cursorY, springCfg);

  useEffect(() => {
    const move = (e: MouseEvent) => {
      cursorX.set(e.clientX);
      cursorY.set(e.clientY);
    };
    const over = (e: MouseEvent) => {
      const t = e.target as HTMLElement;
      isHovering.current = !!(t.closest("button,a,[role=button],[data-hover]"));
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseover", over);
    return () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseover", over);
    };
  }, [cursorX, cursorY]);

  return (
    <div className="hidden md:block">
      {/* Outer glow ring */}
      <motion.div
        className="pointer-events-none fixed z-[9999] rounded-full"
        style={{
          x: springX,
          y: springY,
          translateX: "-50%",
          translateY: "-50%",
          width: 36,
          height: 36,
          border: "1.5px solid rgba(0,194,255,0.5)",
          background: "rgba(0,194,255,0.04)",
          backdropFilter: "blur(2px)",
        }}
      />
      {/* Inner dot */}
      <motion.div
        className="pointer-events-none fixed z-[9999] rounded-full"
        style={{
          x: cursorX,
          y: cursorY,
          translateX: "-50%",
          translateY: "-50%",
          width: 6,
          height: 6,
          background: "#00c2ff",
          boxShadow: "0 0 10px 2px rgba(0,194,255,0.7)",
        }}
      />
    </div>
  );
}
