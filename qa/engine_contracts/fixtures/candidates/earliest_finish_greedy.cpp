// Fixture: earliest-finish greedy (REFUTED for the weighted objective).
// fake-behavior: earliest_finish_greedy
// Correct for unweighted cardinality; ignores reward weight in the exchange.
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
        jobs[i] = {f, s, w};
    }
    sort(jobs.begin(), jobs.end());
    long long total = 0;
    long long lastFinish = LLONG_MIN;
    for (auto [f, s, w] : jobs) {
        if (s >= lastFinish) {           // greedy takes the earliest finish
            total += w;
            lastFinish = f;
        }
    }
    cout << total << "\n";
    return 0;
}
