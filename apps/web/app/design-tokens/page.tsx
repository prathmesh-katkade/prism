import type { CSSProperties } from "react";
import { tokens } from "@prism/design-system/tokens";
import "../design-tokens.css";

const colors = [
  ["Canvas", tokens.color.canvas], ["Surface", tokens.color.surface], ["Raised", tokens.color.surfaceRaised],
  ["Border", tokens.color.border], ["Text", tokens.color.textPrimary], ["Secondary", tokens.color.textSecondary],
  ["Completed", tokens.color.completed], ["Blocked", tokens.color.blocked], ["Running", tokens.color.running],
  ["Recorded", tokens.color.recorded]
] as const;
const spaces = Object.entries(tokens.space);
const radii = Object.entries(tokens.radius);

function ThemePanel({ theme }: { theme: "dark" | "light" }) {
  return <section className="token-specimen__panel" data-atlas-theme={theme} aria-label={`${theme} token specimen`}>
    <h2>{theme === "dark" ? "Dark analytical surface" : "Light analytical surface"}</h2>
    <div className="token-specimen__swatches">
      {colors.map(([label, color]) => <div key={label} className="token-specimen__swatch" style={{ "--swatch": color } as CSSProperties}>{label}</div>)}
    </div>
    <div className="token-specimen__section">
      <h3>Type roles</h3>
      <div className="token-specimen__text-samples">
        <div className="token-specimen__hero">Command-center headline</div>
        <div className="token-specimen__display">Evidence before emphasis</div>
        <div className="token-specimen__metric">90 / 90 | metric</div>
        <div className="token-specimen__section-type">Section heading</div>
        <div className="token-specimen__body">Body copy with enough detail to make a careful analytical decision.</div>
        <div className="token-specimen__caption">CAPTION | explanatory metadata</div>
        <div className="token-specimen__data">RECORDED | 90/90 | 1.66 s</div>
      </div>
    </div>
    <div className="token-specimen__section">
      <h3>Spacing scale</h3>
      <div className="token-specimen__scale">{spaces.map(([step, value]) => <div key={step} className="token-specimen__space-row">
        <span>{step}</span><i className="token-specimen__space-bar" style={{ "--sample-size": value } as CSSProperties} />
      </div>)}</div>
    </div>
    <div className="token-specimen__section">
      <h3>Radii and density</h3>
      <div className="token-specimen__radii">{radii.map(([name, value]) => <div key={name} className="token-specimen__radius" style={{ borderRadius: value }}>{name}</div>)}</div>
      <table className="token-specimen__density">
        <tbody>
          <tr style={{ "--row-height": tokens.density.compactRow } as CSSProperties}><td>Compact analytical row</td><td>34 px</td></tr>
          <tr style={{ "--row-height": tokens.density.standardRow } as CSSProperties}><td>Standard interactive row</td><td>40 px</td></tr>
        </tbody>
      </table>
    </div>
  </section>;
}

export default function DesignTokensPage() {
  return <main className="token-specimen__page">
    <header className="token-specimen__heading">
      <h1>Atlas design tokens</h1>
      <p>Shared semantic tokens for analytical surfaces. Theme colors change meaningfully; state color stays separate from neutral chrome.</p>
    </header>
    <div className="token-specimen__themes"><ThemePanel theme="dark" /><ThemePanel theme="light" /></div>
  </main>;
}
