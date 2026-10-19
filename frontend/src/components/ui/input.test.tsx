import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Input } from "./input";

describe("Input", () => {
  it("renders an input element with default classes", () => {
    render(<Input data-testid="test-input" />);
    const input = screen.getByTestId("test-input") as HTMLInputElement;
    expect(input).toBeInTheDocument();
    expect(input.tagName).toBe("INPUT");
  });

  it("sets data-slot to 'input'", () => {
    render(<Input data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    expect(input).toHaveAttribute("data-slot", "input");
  });

  it("forwards the type prop", () => {
    render(<Input type="email" data-testid="test-input" />);
    const input = screen.getByTestId("test-input") as HTMLInputElement;
    expect(input.type).toBe("email");
  });

  it("renders with type text by default", () => {
    render(<Input data-testid="test-input" />);
    const input = screen.getByTestId("test-input") as HTMLInputElement;
    expect(input.type).toBe("text");
  });

  it("forwards standard input attributes", () => {
    render(
      <Input
        placeholder="Enter text"
        disabled
        data-testid="test-input"
      />
    );
    const input = screen.getByTestId("test-input") as HTMLInputElement;
    expect(input.placeholder).toBe("Enter text");
    expect(input.disabled).toBe(true);
  });

  it("forwards value prop", () => {
    render(<Input value="hello" readOnly data-testid="test-input" />);
    const input = screen.getByTestId("test-input") as HTMLInputElement;
    expect(input.value).toBe("hello");
  });

  it("calls onChange when input value changes", () => {
    const onChange = vi.fn();
    render(<Input onChange={onChange} data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    fireEvent.change(input, { target: { value: "new text" } });
    expect(onChange).toHaveBeenCalled();
  });

  it("responds to blur events", () => {
    const onBlur = vi.fn();
    render(<Input onBlur={onBlur} data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    fireEvent.blur(input);
    expect(onBlur).toHaveBeenCalled();
  });

  it("responds to focus events", () => {
    const onFocus = vi.fn();
    render(<Input onFocus={onFocus} data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    fireEvent.focus(input);
    expect(onFocus).toHaveBeenCalled();
  });

  it("merges custom className with default classes", () => {
    render(<Input className="custom-class" data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    expect(input).toHaveClass("custom-class");
    expect(input.className).toContain("h-8");
    expect(input.className).toContain("w-full");
  });

  it("renders password input type", () => {
    render(<Input type="password" data-testid="test-input" />);
    const input = screen.getByTestId("test-input") as HTMLInputElement;
    expect(input.type).toBe("password");
  });

  it("renders number input type", () => {
    render(<Input type="number" data-testid="test-input" />);
    const input = screen.getByTestId("test-input") as HTMLInputElement;
    expect(input.type).toBe("number");
  });

  it("renders file input type", () => {
    render(<Input type="file" data-testid="test-input" />);
    const input = screen.getByTestId("test-input") as HTMLInputElement;
    expect(input.type).toBe("file");
  });

  it("renders checkbox input type", () => {
    render(<Input type="checkbox" data-testid="test-input" />);
    const input = screen.getByTestId("test-input") as HTMLInputElement;
    expect(input.type).toBe("checkbox");
  });

  it("forwards aria-invalid attribute", () => {
    render(<Input aria-invalid="true" data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    expect(input).toHaveAttribute("aria-invalid", "true");
  });

  it("forwards aria-invalid false", () => {
    render(<Input aria-invalid="false" data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    expect(input).toHaveAttribute("aria-invalid", "false");
  });

  it("forwards name attribute", () => {
    render(<Input name="email" data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    expect(input).toHaveAttribute("name", "email");
  });

  it("forwards id attribute", () => {
    render(<Input id="input-field" data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    expect(input).toHaveAttribute("id", "input-field");
  });

  it("forwards required attribute", () => {
    render(<Input required data-testid="test-input" />);
    const input = screen.getByTestId("test-input") as HTMLInputElement;
    expect(input.required).toBe(true);
  });

  it("forwards pattern attribute", () => {
    render(<Input pattern="[0-9]+" data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    expect(input).toHaveAttribute("pattern", "[0-9]+");
  });

  it("forwards min and max for number inputs", () => {
    render(
      <Input
        type="number"
        min="0"
        max="100"
        data-testid="test-input"
      />
    );
    const input = screen.getByTestId("test-input");
    expect(input).toHaveAttribute("min", "0");
    expect(input).toHaveAttribute("max", "100");
  });

  it("forwards step for number inputs", () => {
    render(<Input type="number" step="0.01" data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    expect(input).toHaveAttribute("step", "0.01");
  });

  it("forwards accept for file inputs", () => {
    render(<Input type="file" accept="image/*" data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    expect(input).toHaveAttribute("accept", "image/*");
  });

  it("forwards autoComplete attribute", () => {
    render(<Input autoComplete="email" data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    expect(input).toHaveAttribute("autocomplete", "email");
  });

  it("includes border-input class in className", () => {
    render(<Input data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    expect(input.className).toContain("border-input");
  });

  it("includes transition-colors in className", () => {
    render(<Input data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    expect(input.className).toContain("transition-colors");
  });

  it("includes focus-visible classes", () => {
    render(<Input data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    expect(input.className).toContain("focus-visible");
  });

  it("includes disabled state classes", () => {
    render(<Input disabled data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    expect(input.className).toContain("disabled:pointer-events-none");
    expect(input.className).toContain("disabled:cursor-not-allowed");
  });

  it("includes placeholder styling", () => {
    render(<Input placeholder="Type here" data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    expect(input.className).toContain("placeholder:text-muted-foreground");
  });

  it("forwards readOnly attribute", () => {
    render(<Input readOnly value="static" data-testid="test-input" />);
    const input = screen.getByTestId("test-input") as HTMLInputElement;
    expect(input.readOnly).toBe(true);
  });

  it("forwards onClick handler", () => {
    const onClick = vi.fn();
    render(<Input onClick={onClick} data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    fireEvent.click(input);
    expect(onClick).toHaveBeenCalled();
  });

  it("forwards onKeyDown handler", () => {
    const onKeyDown = vi.fn();
    render(<Input onKeyDown={onKeyDown} data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onKeyDown).toHaveBeenCalled();
  });

  it("renders with multiple custom classes", () => {
    render(<Input className="class1 class2 class3" data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    expect(input).toHaveClass("class1", "class2", "class3");
  });

  it("does not render type as a class name", () => {
    render(<Input type="email" data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    expect(input.className).not.toContain("email");
  });

  it("forwards inputMode attribute", () => {
    render(<Input inputMode="numeric" data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    expect(input).toHaveAttribute("inputmode", "numeric");
  });

  it("forwards maxLength attribute", () => {
    render(<Input maxLength={50} data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    expect(input).toHaveAttribute("maxlength", "50");
  });

  it("forwards minLength attribute", () => {
    render(<Input minLength={5} data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    expect(input).toHaveAttribute("minlength", "5");
  });

  it("includes aria-invalid destructive styling in className", () => {
    render(<Input aria-invalid="true" data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    expect(input.className).toContain("aria-invalid:border-destructive");
    expect(input.className).toContain("aria-invalid:ring-destructive");
  });

  it("forwards onKeyUp handler", () => {
    const onKeyUp = vi.fn();
    render(<Input onKeyUp={onKeyUp} data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    fireEvent.keyUp(input, { key: "a" });
    expect(onKeyUp).toHaveBeenCalled();
  });

  it("forwards onInput handler", () => {
    const onInput = vi.fn();
    render(<Input onInput={onInput} data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    fireEvent.input(input, { target: { value: "test" } });
    expect(onInput).toHaveBeenCalled();
  });

  it("renders with default empty value", () => {
    render(<Input data-testid="test-input" />);
    const input = screen.getByTestId("test-input") as HTMLInputElement;
    expect(input.value).toBe("");
  });

  it("forwards spellCheck attribute", () => {
    render(<Input spellCheck="false" data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    expect(input).toHaveAttribute("spellcheck", "false");
  });

  it("includes file input styling in className", () => {
    render(<Input type="file" data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    expect(input.className).toContain("file:");
  });

  it("forwards defaultValue prop", () => {
    render(<Input defaultValue="initial" data-testid="test-input" />);
    const input = screen.getByTestId("test-input") as HTMLInputElement;
    expect(input.value).toBe("initial");
  });

  it("forwards multiple event handlers together", () => {
    const onChange = vi.fn();
    const onFocus = vi.fn();
    const onBlur = vi.fn();
    render(
      <Input
        onChange={onChange}
        onFocus={onFocus}
        onBlur={onBlur}
        data-testid="test-input"
      />
    );
    const input = screen.getByTestId("test-input");
    fireEvent.focus(input);
    expect(onFocus).toHaveBeenCalledTimes(1);
    fireEvent.change(input, { target: { value: "text" } });
    expect(onChange).toHaveBeenCalledTimes(1);
    fireEvent.blur(input);
    expect(onBlur).toHaveBeenCalledTimes(1);
  });

  it("preserves className order when merging", () => {
    render(<Input className="extra" data-testid="test-input" />);
    const input = screen.getByTestId("test-input") as HTMLInputElement;
    expect(input.className.length).toBeGreaterThan(0);
    expect(input.className).toContain("extra");
  });

  it("renders with type undefined defaults to text", () => {
    const { rerender } = render(<Input data-testid="test-input" />);
    let input = screen.getByTestId("test-input") as HTMLInputElement;
    expect(input.type).toBe("text");

    rerender(<Input type={undefined} data-testid="test-input" />);
    input = screen.getByTestId("test-input") as HTMLInputElement;
    expect(input.type).toBe("text");
  });

  it("includes rounded-lg class for border radius", () => {
    render(<Input data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    expect(input.className).toContain("rounded-lg");
  });

  it("includes bg-transparent class", () => {
    render(<Input data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    expect(input.className).toContain("bg-transparent");
  });

  it("includes outline-none class", () => {
    render(<Input data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    expect(input.className).toContain("outline-none");
  });

  it("includes dark mode classes", () => {
    render(<Input data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    expect(input.className).toContain("dark:");
  });

  it("renders with dir attribute for text direction", () => {
    render(<Input dir="rtl" data-testid="test-input" />);
    const input = screen.getByTestId("test-input");
    expect(input).toHaveAttribute("dir", "rtl");
  });
});
