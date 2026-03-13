"use client";

interface ProbabilityBarProps {
  value: number; // 0-1
  color?: string;
  height?: number;
}

export default function ProbabilityBar({
  value,
  color = "bg-emerald-500",
  height = 20,
}: ProbabilityBarProps) {
  const pct = Math.round(value * 100);
  return (
    <div
      className="flex items-center gap-2"
      style={{ minWidth: 120 }}
    >
      <div
        className="bg-gray-800 rounded-full overflow-hidden flex-1"
        style={{ height }}
      >
        <div
          className={`${color} rounded-full h-full transition-all duration-300`}
          style={{ width: `${Math.max(pct, 1)}%` }}
        />
      </div>
      <span className="text-xs text-gray-400 w-10 text-right font-mono">
        {pct}%
      </span>
    </div>
  );
}
