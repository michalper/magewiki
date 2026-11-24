export const instant = false;

import type { Metadata } from "next";
import UpgradeImpactClient from "./UpgradeImpactClient";

export const metadata: Metadata = { title: "Upgrade impact" };

export default function UpgradeImpactPage() {
  return <UpgradeImpactClient />;
}
