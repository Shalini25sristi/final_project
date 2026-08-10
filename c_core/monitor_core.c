#include <math.h>
#include <stdint.h>
#include <stdlib.h>

#ifdef _WIN32
#define API __declspec(dllexport)
#else
#define API
#endif

typedef struct {
    int second;
    double memory_mb;
    double cpu_percent;
    uint32_t random_state;
    int history_size;
    int count;
    double* memory_history;
    double* cpu_history;
} MonitorState;

typedef struct {
    int second;
    double memory_mb;
    double cpu_percent;
    int score;
    int leak;
} MonitorData;

static double clamp(double value, double minimum, double maximum) {
    if (value < minimum) {
        return minimum;
    }
    if (value > maximum) {
        return maximum;
    }
    return value;
}

static uint32_t next_random_raw(MonitorState* state) {
    state->random_state = state->random_state * 1664525u + 1013904223u;
    return state->random_state;
}

static double random_range(MonitorState* state, double minimum, double maximum) {
    double part = (double)(next_random_raw(state) & 0x00FFFFFFu) / (double)0x01000000u;
    return minimum + (maximum - minimum) * part;
}

static double feature_value(MonitorState* state, int index, int feature) {
    if (feature == 0) {
        return state->memory_history[index];
    }
    return state->cpu_history[index];
}

static void push_history(MonitorState* state, double memory_mb, double cpu_percent) {
    int i;

    if (state->count < state->history_size) {
        state->memory_history[state->count] = memory_mb;
        state->cpu_history[state->count] = cpu_percent;
        state->count += 1;
        return;
    }

    for (i = 1; i < state->history_size; i++) {
        state->memory_history[i - 1] = state->memory_history[i];
        state->cpu_history[i - 1] = state->cpu_history[i];
    }

    state->memory_history[state->history_size - 1] = memory_mb;
    state->cpu_history[state->history_size - 1] = cpu_percent;
}

static double average_path_length(int size) {
    if (size <= 1) {
        return 0.0;
    }
    if (size == 2) {
        return 1.0;
    }
    return 2.0 * (log((double)(size - 1)) + 0.5772156649) - (2.0 * (size - 1) / (double)size);
}

static double isolation_path(
    MonitorState* state,
    int* indices,
    int size,
    int depth,
    int max_depth,
    double target_memory,
    double target_cpu
) {
    int i;
    int feature;
    int left_count = 0;
    int right_count = 0;
    double min_value;
    double max_value;
    double split_value;
    double target_value;
    int* left_indices;
    int* right_indices;
    double result;

    if (size <= 1 || depth >= max_depth) {
        return depth + average_path_length(size);
    }

    feature = (int)(next_random_raw(state) % 2u);
    min_value = feature_value(state, indices[0], feature);
    max_value = min_value;

    for (i = 1; i < size; i++) {
        double value = feature_value(state, indices[i], feature);
        if (value < min_value) {
            min_value = value;
        }
        if (value > max_value) {
            max_value = value;
        }
    }

    if (max_value - min_value < 1e-9) {
        return depth + average_path_length(size);
    }

    split_value = random_range(state, min_value, max_value);
    target_value = feature == 0 ? target_memory : target_cpu;

    left_indices = (int*)malloc((size_t)size * sizeof(int));
    right_indices = (int*)malloc((size_t)size * sizeof(int));
    if (!left_indices || !right_indices) {
        free(left_indices);
        free(right_indices);
        return depth + average_path_length(size);
    }

    for (i = 0; i < size; i++) {
        double value = feature_value(state, indices[i], feature);
        if (value < split_value) {
            left_indices[left_count] = indices[i];
            left_count += 1;
        } else {
            right_indices[right_count] = indices[i];
            right_count += 1;
        }
    }

    if (target_value < split_value) {
        if (left_count == 0) {
            result = depth + 1.0;
        } else {
            result = isolation_path(
                state,
                left_indices,
                left_count,
                depth + 1,
                max_depth,
                target_memory,
                target_cpu
            );
        }
    } else {
        if (right_count == 0) {
            result = depth + 1.0;
        } else {
            result = isolation_path(
                state,
                right_indices,
                right_count,
                depth + 1,
                max_depth,
                target_memory,
                target_cpu
            );
        }
    }

    free(left_indices);
    free(right_indices);
    return result;
}

static double isolation_score(
    MonitorState* state,
    double target_memory,
    double target_cpu
) {
    const int tree_count = 8;
    const int sample_limit = 8;
    const int max_depth = 4;
    int tree;
    int sample_size;
    double path_sum = 0.0;

    if (state->count < 4) {
        return 0.0;
    }

    sample_size = state->count < sample_limit ? state->count : sample_limit;

    for (tree = 0; tree < tree_count; tree++) {
        int i;
        int* pool;
        int* sample_indices;

        pool = (int*)malloc((size_t)state->count * sizeof(int));
        sample_indices = (int*)malloc((size_t)sample_size * sizeof(int));
        if (!pool || !sample_indices) {
            free(pool);
            free(sample_indices);
            return 0.0;
        }

        for (i = 0; i < state->count; i++) {
            pool[i] = i;
        }

        for (i = 0; i < sample_size; i++) {
            int j = i + (int)(next_random_raw(state) % (uint32_t)(state->count - i));
            int temp = pool[i];
            pool[i] = pool[j];
            pool[j] = temp;
            sample_indices[i] = pool[i];
        }

        path_sum += isolation_path(
            state,
            sample_indices,
            sample_size,
            0,
            max_depth,
            target_memory,
            target_cpu
        );

        free(pool);
        free(sample_indices);
    }

    return pow(2.0, -(path_sum / tree_count) / average_path_length(sample_size));
}

API int init_monitor(MonitorState* state, unsigned int seed) {
    if (!state) {
        return 0;
    }

    state->second = 0;
    state->memory_mb = 240.0;
    state->cpu_percent = 25.0;
    state->random_state = seed == 0 ? 1u : seed;
    state->history_size = 24;
    state->count = 0;
    state->memory_history = (double*)malloc((size_t)state->history_size * sizeof(double));
    state->cpu_history = (double*)malloc((size_t)state->history_size * sizeof(double));

    if (!state->memory_history || !state->cpu_history) {
        free(state->memory_history);
        free(state->cpu_history);
        state->memory_history = NULL;
        state->cpu_history = NULL;
        return 0;
    }

    return 1;
}

API void free_monitor(MonitorState* state) {
    if (!state) {
        return;
    }

    free(state->memory_history);
    free(state->cpu_history);
    state->memory_history = NULL;
    state->cpu_history = NULL;
    state->count = 0;
}

API int next_monitor_data(MonitorState* state, double threshold, MonitorData* out) {
    int score;
    int leak;
    double score_value;

    if (!state || !out || !state->memory_history || !state->cpu_history) {
        return 0;
    }

    if (threshold <= 0.0) {
        threshold = 420.0;
    }

    state->second += 1;
    state->memory_mb += random_range(state, -5.0, 12.0);
    state->cpu_percent += random_range(state, -4.0, 8.0);

    state->memory_mb = clamp(state->memory_mb, 180.0, 700.0);
    state->cpu_percent = clamp(state->cpu_percent, 5.0, 100.0);

    push_history(state, state->memory_mb, state->cpu_percent);

    score_value = isolation_score(state, state->memory_mb, state->cpu_percent);
    score = (int)(score_value * 100.0);

    if (state->memory_mb > threshold) {
        score += 20;
    }
    if (score > 100) {
        score = 100;
    }

    leak = score >= 60;

    out->second = state->second;
    out->memory_mb = state->memory_mb;
    out->cpu_percent = state->cpu_percent;
    out->score = score;
    out->leak = leak;
    return 1;
}
