// Fixture: DP with a real base/indexing error (not the empty-choice label).
// fake-behavior: dp_base_error
// dp[p + 1] reads the wrong prefix, so a single best job can be missed.
#include <bits/stdc++.h>
using namespace std;

int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    int n;
    if (!(cin >> n)) return 0;
    vector<tuple<long long,long long,long long>> jobs;
    for (int i = 0; i < n; ++i) {
        long long s, f, w;
        cin >> s >> f >> w;
        jobs.push_back({f, s, w});
    }
    sort(jobs.begin(), jobs.end());
    vector<long long> finishes(n);
    for (int i = 0; i < n; ++i) finishes[i] = get<0>(jobs[i]);
    vector<long long> dp(n + 1, 0);
    for (int i = 1; i <= n; ++i) {
        long long s = get<1>(jobs[i - 1]);
        long long w = get<2>(jobs[i - 1]);
        int p = int(upper_bound(finishes.begin(), finishes.begin() + (i - 1), s) - finishes.begin());
        dp[i] = max(dp[i - 1], w + dp[min(p + 1, i - 1)]); // BUG: wrong index
    }
    cout << dp[n] << "\n";
    return 0;
}
