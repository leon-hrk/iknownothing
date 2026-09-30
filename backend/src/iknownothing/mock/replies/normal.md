## Normal reply

This reply comes from the **mock AI client**. No tokens were used. It covers the Markdown the tutor
produces, so the chat can be tested with long, varied replies.

### Lists

1. First step, with `inline code` and *emphasis*
2. Second step
   - a nested point
   - another nested point
3. Third step, which is long enough to wrap onto a second line in a narrow chat column so that line
   height and indentation of wrapped list items can be checked.

### Math

Inline math with dollars: $F(s) = \int_0^\infty f(t)\,e^{-st}\,dt$, and with parentheses: \(a^2 + b^2 = c^2\).

Display math with dollars:

$$
\mathcal{L}\{f'(t)\} = s\,F(s) - f(0)
$$

Display math with brackets:

\[
\sum_{k=0}^{n} \binom{n}{k} x^k = (1 + x)^n
\]

### Table

| Function $f(t)$ | Transform $F(s)$ | Region |
|---|---|---|
| $1$ | $\frac{1}{s}$ | $s > 0$ |
| $e^{at}$ | $\frac{1}{s-a}$ | $s > a$ |
| $\sin(\omega t)$ | $\frac{\omega}{s^2+\omega^2}$ | $s > 0$ |

### Code

```python
def laplace(f, s, dt=1e-3, T=50):
    return sum(f(t) * math.exp(-s * t) * dt for t in frange(0, T, dt))
```

### Diagram

```
  x(t) ──► [ H(s) ] ──► y(t)
              ▲
              │
           feedback
```

### Quote

> A quoted hint, as the tutor gives it before showing a solution.

### Edge cases

A price of $5 and another of $10 in one sentence.

That's the end of the long reply.