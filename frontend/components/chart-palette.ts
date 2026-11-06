"use client";

import { useTheme } from "next-themes";
import { useMounted } from "@/lib/use-mounted";

// Validated default reference palette (see the dataviz skill's palette.md) —
// used verbatim, not re-derived, so no re-validation is needed here.
const CATEGORICAL_LIGHT = [
  "#2a78d6",
  "#eb6834",
  "#1baf7a",
  "#eda100",
  "#e87ba4",
  "#008300",
  "#6250d6",
  "#e34948",
];
const CATEGORICAL_DARK = [
  "#3987e5",
  "#d95926",
  "#199e70",
  "#c98500",
  "#d55181",
  "#008300",
  "#9085e9",
  "#e66767",
];

const STATUS = {
  good: "#0ca30c",
  warning: "#fab219",
  serious: "#ec835a",
  critical: "#d03b3b",
};

const SEQUENTIAL_BLUE = { light: "#2a78d6", dark: "#3987e5" };

const INK_LIGHT = { primary: "#0b0b0b", secondary: "#52514e", muted: "#898781", gridline: "#e1e0d9" };
const INK_DARK = { primary: "#f0efec", secondary: "#c3c2b7", muted: "#898781", gridline: "#2c2c2a" };

export function useChartPalette() {
  const { resolvedTheme } = useTheme();
  const mounted = useMounted();
  const isDark = mounted && resolvedTheme === "dark";

  return {
    categorical: isDark ? CATEGORICAL_DARK : CATEGORICAL_LIGHT,
    status: STATUS, // same steps in both modes per palette.md
    sequential: isDark ? SEQUENTIAL_BLUE.dark : SEQUENTIAL_BLUE.light,
    ink: isDark ? INK_DARK : INK_LIGHT,
    track: isDark ? "#383835" : "#f0efec", // unfilled remainder of a progress ring
  };
}
