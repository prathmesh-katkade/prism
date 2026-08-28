import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PrismShell } from "./prism-shell";

describe("PRISM shell", () => {
  it("opens the universal command surface with the keyboard", async () => {
    render(<PrismShell />);
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(screen.getByRole("dialog", { name: "PRISM command surface" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Search commands" })).toHaveFocus());
  });

  it("opens native Overview and SQL Lab while later workspaces remain legacy bridges", () => {
    render(<PrismShell />);
    fireEvent.click(screen.getAllByRole("button", { name: /Overview native/i })[0]!);
    expect(screen.getByText("Start with the dataset, then follow the evidence.")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: /SQL Lab native/i })[0]!);
    expect(screen.getByText("Preparing Query Studio")).toBeInTheDocument();
  });

  it("keeps the inspector available as contextual shell state", () => {
    render(<PrismShell />);
    expect(screen.getByRole("complementary", { name: "Contextual inspector" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Hide inspector" }));
    expect(screen.getByRole("button", { name: "Show inspector" })).toBeInTheDocument();
  });

  it("keeps the native Overview upload action available to keyboard users", () => {
    render(<PrismShell />);
    fireEvent.click(screen.getAllByRole("button", { name: /Overview native/i })[0]!);
    const upload = screen.getByLabelText("Choose dataset");
    upload.focus();
    expect(upload).toHaveFocus();
  });
});
