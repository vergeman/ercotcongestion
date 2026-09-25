# Sidebar Constraints Cheat Sheet

The Constraints sidebar ranks **which constraints drove congestion on the
delivery day currently under the scrubber**. It does **not** aggregate over the
scrubber's loaded date range, and it does not use only the cursor hour.

## Shadow-price basis

- **Realized:** ERCOT's published Day-Ahead Market (DAM) constraint shadow
  prices from **NP4-191-CD** (*Day-Ahead Market Binding Constraint Data*).
- **Predicted:** the model's expected hourly constraint shadow price:

  ```text
  E[mu] = P(bind) x E[mu | bind]
  ```

  `P(bind)` is the probability that the constraint binds in that hour;
  `E[mu | bind]` is its expected shadow-price severity if it binds.

## Ranking calculations

For every constraint, across every hour in the scrubber's selected delivery
day (23, 24, or 25 hours):

```text
mu mass = sum over delivery-day hours of |hourly mu|
```

- For **Predicted**, hourly `mu` is `P(bind) x E[mu | bind]`.
- For **Realized**, hourly `mu` is ERCOT's published DAM shadow price.

```text
SF reach = sum over all settlement points of |SF[constraint, node]|
```

SF is the fitted shift-factor map. The absolute sum means negative- and
positive-SF effects do not cancel. SF reach is structural, so it is the same
for Predicted and Realized.

```text
contribution = mu mass x SF reach
```

Constraints are ranked by this contribution score. It is a day-level measure
of a constraint's expected or realized nodal-congestion impact.
