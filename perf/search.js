// The search's baseline under load (docs/REARCHITECTURE.md, phase 4), for k6:
//
//   docker run --rm --network host -e CARO_BASE=http://127.0.0.1:8000 \
//     -v "$PWD/perf:/perf" grafana/k6 run /perf/search.js
//
// Ten users at once, for a minute by default, each asking the search one of
// the questions the site's own checks ask, in turn, with no pause: what one
// API process answers when it is kept busy. The target is docs/PERF.md's,
// and the run fails when it is not met: the 95th percentile of a search
// under the target, and no more than one answer in a hundred failed.
import http from 'k6/http';
import { check } from 'k6';

const BASE = __ENV.CARO_BASE || 'http://127.0.0.1:8000';
const P95_MS = Number(__ENV.CARO_P95_MS || 300);

export const options = {
  vus: Number(__ENV.CARO_VUS || 10),
  duration: __ENV.CARO_DURATION || '60s',
  thresholds: {
    'http_req_duration{name:search}': [`p(95)<${P95_MS}`],
    http_req_failed: ['rate<0.01'],
  },
  summaryTrendStats: ['min', 'med', 'avg', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

const QUESTIONS = [
  'سمند زیر ۲ میلیارد',
  'پژو ۲۰۶ تیپ ۲',
  'پراید کم کارکرد',
  'دنا پلاس اتوماتیک',
  'تیبا ۲ مدل ۱۴۰۰',
  'پژو پارس بدون رنگ',
  'ساینا زیر یک میلیارد',
  'هایما اس ۷',
];

export default function () {
  const q = QUESTIONS[(__VU + __ITER) % QUESTIONS.length];
  const r = http.get(`${BASE}/api/search?q=${encodeURIComponent(q)}`, { tags: { name: 'search' } });
  check(r, { 'answered 200': (x) => x.status === 200 });
}
