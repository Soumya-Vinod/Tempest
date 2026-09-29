// "About the data": every data source, model and known limit, in plain words. The one place to
// update when an input changes (Dev A's hazard inputs included). Shown collapsed at the bottom
// of the side panel; a short version is in README.md.

/** The honest framing of the countdown: shown in its panel section and under limits below. */
export const FORECAST_FRAMING =
  'Facilities are flagged when their cut-off falls within the 24 h forecast window. Real ' +
  'warning time depends on forecast accuracy; this replay uses the observed storm as a ' +
  'perfect forecast.'

export interface SourceItem {
  name: string
  detail: string
}

export interface SourceGroup {
  title: string
  items: SourceItem[]
}

export const ABOUT_THE_DATA: SourceGroup[] = [
  {
    title: 'Real data',
    items: [
      {
        name: 'Infrastructure',
        detail:
          'OpenStreetMap roads, ferries, power lines, substations, hospitals and buildings, ' +
          'downloaded through Overpass on 25 Sep 2026 (ODbL).',
      },
      {
        name: 'Cyclone track',
        detail:
          'IBTrACS best track for Cyclone Amphan (storm 2020136N10088): position, maximum ' +
          'wind and central pressure every 3 hours.',
      },
      {
        name: 'Elevation',
        detail:
          'SRTM (NASA, 1 arc-second), sampled at 90 m and averaged over each 5.5 km hazard cell.',
      },
      {
        name: 'Population',
        detail:
          'Census of India 2011 population per CD block, taken from Wikidata, which cites the ' +
          'Census Primary Census Abstract (the Census file itself was unreachable).',
      },
      {
        name: 'Block boundaries',
        detail:
          'geoBoundaries (India, level 3) for the 29 South 24 Parganas CD blocks, matched to ' +
          'Census 2011 codes (ODbL).',
      },
      {
        name: 'Protected areas',
        detail:
          'OpenStreetMap protected areas (the Sundarbans reserve forest), same download date. ' +
          'Risk counts only the inhabited land outside them.',
      },
    ],
  },
  {
    title: 'Modelled',
    items: [
      {
        name: 'Wind',
        detail:
          'Holland parametric wind profile around the IBTrACS track, with a wider outer wind ' +
          'envelope beyond the storm core.',
      },
      {
        name: 'Storm surge',
        detail:
          'Parametric: pressure drop plus wind set-up at the coast, decaying inland and ' +
          'reduced by ground elevation. Not a hydrodynamic model.',
      },
      {
        name: 'Flood susceptibility',
        detail:
          'A weighted index of six inputs. Elevation, slope and local depressions come from ' +
          'SRTM. Surface water, rainfall and land cover are simplified proxies (distance to ' +
          'the coast, and latitude bands), not the JRC, IMERG or WorldCover datasets. Static: ' +
          'the same at every timestep.',
      },
      {
        name: 'Impact and risk',
        detail:
          "Tempest's own engine: which roads, ferries, substations and facilities each " +
          'hazard cuts or isolates, and a 0–1 risk score per block from hazard, exposure and ' +
          'vulnerability.',
      },
      {
        name: 'People in the surge zone',
        detail:
          "An estimate: each block's 2011 population, spread evenly over its inhabited land, " +
          'times the share of that land with at least 0.3 m of surge. Summed for the district. ' +
          'In the Next 24 h view it is the worst case over the next 24 h.',
      },
    ],
  },
  {
    title: 'Approximations and limits',
    items: [
      {
        name: 'Replay only',
        detail: 'Tempest runs on the 2020 Amphan replay; live mode is not implemented.',
      },
      {
        name: 'Hazard grid',
        detail: 'Hazards are computed on 0.05° cells, about 5.5 km across.',
      },
      {
        name: 'Distance to coast',
        detail:
          'Distance to coast is measured to a simplified straight coastline, not the real ' +
          'Sundarbans shoreline; surge fades inland based on it.',
      },
      {
        name: 'Next 24 h view',
        detail:
          "A perfect-forecast replay: the worst hazard in each cell over the next 24 h of " +
          "the replay itself, not a real forecast. Operationally it would come from IMD's " +
          'forecast track.',
      },
      {
        name: 'Warning time',
        detail: FORECAST_FRAMING,
      },
      {
        name: 'Shelters',
        detail:
          'OpenStreetMap has no designated cyclone shelters in this area, so schools, ' +
          'community centres and public buildings are shown as stand-ins.',
      },
      {
        name: 'Hospitals',
        detail:
          'The OpenStreetMap health facilities include nursing homes and small clinics, not ' +
          'only hospitals.',
      },
      {
        name: 'Insurance',
        detail:
          'The parametric payouts are illustrative: not an actual policy. Payouts follow the ' +
          'hazard reading, not assessed losses.',
      },
      {
        name: 'Literacy',
        detail:
          'Not used in the vulnerability score: the Census file with block literacy was ' +
          'unreachable and no other source was found.',
      },
    ],
  },
  {
    title: 'AI use',
    items: [
      {
        name: 'Drafting',
        detail:
          'Advisories are drafted by Gemini 3.7 Flash, or by Groq (openai/gpt-oss-120b) when ' +
          'Gemini is unavailable. Each draft shows which model wrote it.',
      },
      {
        name: 'Numbers',
        detail:
          'Every figure in an advisory comes from the engine. The model writes placeholders, ' +
          'the server fills them in, and drafts with numbers of their own are rejected.',
      },
      {
        name: 'Approval',
        detail: 'A named official approves every advisory before it can be sent.',
      },
    ],
  },
]
