export const instant = false;

import type { Metadata } from "next";
import CompareClient from "./CompareClient";

export const metadata: Metadata = { title: "Compare modules" };

export default function ComparePage() {
  return <CompareClient />;
}
