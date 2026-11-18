// Fixture: an unconventional but correct coordinate sweep (control).
// fake-behavior: sweep_line_correct
// This must survive review; it is not rejected for being nonstandard.
#include <bits/stdc++.h>
using namespace std;

int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    int n;
    if (!(cin >> n)) return 0;
    vector<tuple<long long,long long,long long>> jobs(n);
    for (int i = 0; i < n; ++i) {
        long long s, f, w;
        cin >> s >> f >> w;
        jobs[i] = {s, f, w};
    }
    vector<long long> xs;
    for (auto [s, f, w] : jobs) { xs.push_back(s); xs.push_back(f); }
    xs.push_back(0);
    sort(xs.begin(), xs.end());
    xs.erase(unique(xs.begin(), xs.end()), xs.end());
    auto idx = [&](long long v) { return int(lower_bound(xs.begin(), xs.end(), v) - xs.begin()); };
    vector<pair<long long,long long>> byFinish;
    for (auto [s, f, w] : jobs) byFinish.push_back({idx(f), w});
    vector<vector<long long>> ending(xs.size());
    for (auto [s, f, w] : jobs) ending[idx(f)].push_back(w * 1000000000LL + idx(s));
    vector<long long> best(xs.size(), 0);
    for (size_t i = 1; i < xs.size(); ++i) {
        best[i] = best[i - 1];
        for (long long packed : ending[i]) {
            long long w = packed / 1000000000LL;
            int p = int(packed % 1000000000LL);
            best[i] = max(best[i], w + best[p]);
        }
    }
    cout << best.back() << "\n";
    return 0;
}
