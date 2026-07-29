import { boxStats, jitterOffset, niceScale, pointStyle } from "../lib/boxplot";
import { formatCount, formatInterval, formatProbability } from "../lib/format";
import type { PopulationComparison } from "../lib/types";

/**
 * One population's boxplot: two groups, every observation drawn over the box.
 *
 * A boxplot is five numbers, and on its own it cannot say whether they came from
 * four observations or four hundred. A reader who assumes the latter draws a
 * conclusion the data does not support, so every observation is a point and each
 * group's n is written under its box. Neither is decoration.
 *
 * Drawn as plain SVG. The reasoning, and the matplotlib conventions this
 * matches, are in `lib/boxplot.ts`.
 */

/** The group hues, by position, so `groups[0]` gets the same colour everywhere.
 *
 * Named rather than literal because the light and dark themes use different
 * steps of the same two hues; `styles.css` holds the values and the note on how
 * they were checked. Identity never rests on hue alone: each group is also named
 * under its box, in the legend, and in the statistics table.
 */
export const GROUP_COLOURS = ["var(--series-1)", "var(--series-2)"] as const;

export function groupColour(index: number): string {
  return GROUP_COLOURS[index % GROUP_COLOURS.length] as string;
}

const WIDTH = 260;
const HEIGHT = 268;
const MARGIN = { top: 10, right: 14, bottom: 52, left: 46 };
const PLOT_WIDTH = WIDTH - MARGIN.left - MARGIN.right;
const PLOT_HEIGHT = HEIGHT - MARGIN.top - MARGIN.bottom;
const BOX_WIDTH = 54;
/** Half the horizontal spread of the point cloud, matching `plots.py`'s ±42%
 * of the box width. Wide enough that ties do not stack into a single line. */
const JITTER = 22;

export interface BoxplotProps {
  comparison: PopulationComparison;
  /** Sorted group values; `groups[0]` is the reference the signs point away from. */
  groups: string[];
  splitOn: string;
}

export function Boxplot({
  comparison,
  groups,
  splitOn,
}: BoxplotProps): React.JSX.Element {
  const everyValue = groups.flatMap((group) => comparison.values[group] ?? []);
  const scale = niceScale(everyValue);
  const span = scale.max - scale.min || 1;
  const y = (value: number): number =>
    MARGIN.top + PLOT_HEIGHT - ((value - scale.min) / span) * PLOT_HEIGHT;

  const slot = (index: number): number =>
    MARGIN.left + (PLOT_WIDTH * (index * 2 + 1)) / (groups.length * 2);

  return (
    <figure className="boxplot">
      <figcaption className="boxplot__title">
        <span className="boxplot__population">{comparison.population}</span>
        <span className="boxplot__stats">
          q = {formatProbability(comparison.q_value)} · shift{" "}
          {formatInterval(comparison.shift_ci)} pp
        </span>
      </figcaption>

      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={`${comparison.population} relative frequency by ${splitOn}`}
        className="boxplot__svg"
      >
        {scale.ticks.map((tick) => (
          <g key={tick}>
            <line
              className="boxplot__grid"
              x1={MARGIN.left}
              x2={MARGIN.left + PLOT_WIDTH}
              y1={y(tick)}
              y2={y(tick)}
            />
            <text
              className="boxplot__tick"
              x={MARGIN.left - 7}
              y={y(tick)}
              textAnchor="end"
              dominantBaseline="middle"
            >
              {tick}
            </text>
          </g>
        ))}

        {groups.map((group, index) => {
          const values = comparison.values[group] ?? [];
          const stats = boxStats(values);
          const centre = slot(index);
          const colour = groupColour(index);
          const { radius, opacity } = pointStyle(values.length);

          return (
            <g key={group}>
              {values.map((value, position) => (
                <circle
                  // Values repeat, so identity is the slot the value sits in.
                  key={`${group}-${String(position)}`}
                  className="boxplot__point"
                  cx={
                    centre +
                    jitterOffset(`${comparison.population}-${group}`, position) *
                      JITTER
                  }
                  cy={y(value)}
                  r={radius}
                  fill={colour}
                  opacity={opacity}
                />
              ))}

              {stats !== null && (
                <g className="boxplot__box">
                  <title>
                    {`${splitOn} = ${group}: n ${String(stats.n)}, median ${stats.median.toFixed(2)}%, ` +
                      `quartiles ${stats.q1.toFixed(2)}–${stats.q3.toFixed(2)}%, ` +
                      `range ${stats.min.toFixed(2)}–${stats.max.toFixed(2)}%`}
                  </title>
                  <line
                    className="boxplot__whisker"
                    x1={centre}
                    x2={centre}
                    y1={y(stats.upperWhisker)}
                    y2={y(stats.q3)}
                  />
                  <line
                    className="boxplot__whisker"
                    x1={centre}
                    x2={centre}
                    y1={y(stats.q1)}
                    y2={y(stats.lowerWhisker)}
                  />
                  <line
                    className="boxplot__cap"
                    x1={centre - BOX_WIDTH / 4}
                    x2={centre + BOX_WIDTH / 4}
                    y1={y(stats.upperWhisker)}
                    y2={y(stats.upperWhisker)}
                  />
                  <line
                    className="boxplot__cap"
                    x1={centre - BOX_WIDTH / 4}
                    x2={centre + BOX_WIDTH / 4}
                    y1={y(stats.lowerWhisker)}
                    y2={y(stats.lowerWhisker)}
                  />
                  <rect
                    className="boxplot__rect"
                    x={centre - BOX_WIDTH / 2}
                    width={BOX_WIDTH}
                    y={y(stats.q3)}
                    height={Math.max(1, y(stats.q1) - y(stats.q3))}
                  />
                  <line
                    className="boxplot__median"
                    x1={centre - BOX_WIDTH / 2}
                    x2={centre + BOX_WIDTH / 2}
                    y1={y(stats.median)}
                    y2={y(stats.median)}
                    stroke={colour}
                  />
                </g>
              )}

              <text
                className="boxplot__group"
                x={centre}
                y={MARGIN.top + PLOT_HEIGHT + 20}
                textAnchor="middle"
              >
                {group}
              </text>
              <text
                className="boxplot__n"
                x={centre}
                y={MARGIN.top + PLOT_HEIGHT + 36}
                textAnchor="middle"
              >
                n = {formatCount(comparison.n[group] ?? values.length)}
              </text>
            </g>
          );
        })}
      </svg>
    </figure>
  );
}
