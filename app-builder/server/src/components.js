'use strict';
// Library of ready-made screens. Each component yields one Kotlin file (Jetpack Compose + Material3).
// Kotlin sources use String.raw so backslashes stay literal; only ${...} is interpolated by JS.
// Labels passed through t() must not contain double quotes, backslashes or dollar signs.

const COMMON = String.raw`import android.content.Context
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
`;

const COMPONENTS = {
  counter: {
    id: 'counter',
    keywords: ['عداد', 'عدّاد', 'تسبيح', 'سبحه', 'counter', 'tally', 'clicker'],
    label: { ar: 'العداد', en: 'Counter' },
    icon: '#',
    fn: 'CounterScreen',
    kotlin: (t) => String.raw`${COMMON}
@Composable
fun CounterScreen() {
    val prefs = LocalContext.current.getSharedPreferences("counter", Context.MODE_PRIVATE)
    var count by remember { mutableIntStateOf(prefs.getInt("count", 0)) }
    fun update(v: Int) {
        count = v
        prefs.edit().putInt("count", v).apply()
    }
    Column(
        Modifier.fillMaxSize().padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text("$count", fontSize = 96.sp)
        Spacer(Modifier.height(24.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            Button(onClick = { update(count - 1) }) { Text("-") }
            Button(onClick = { update(count + 1) }) { Text("+") }
        }
        Spacer(Modifier.height(16.dp))
        OutlinedButton(onClick = { update(0) }) { Text("${t('تصفير', 'Reset')}") }
    }
}
`,
  },

  todo: {
    id: 'todo',
    keywords: ['مهام', 'مهمه', 'todo', 'to-do', 'to do', 'task', 'checklist', 'قائمه المهام'],
    label: { ar: 'المهام', en: 'Tasks' },
    icon: '✓',
    fn: 'TodoScreen',
    kotlin: (t) => String.raw`${COMMON}
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.ui.text.style.TextDecoration

private fun loadTodos(p: android.content.SharedPreferences): List<Pair<Boolean, String>> =
    (p.getString("items", "") ?: "").split("\n").filter { it.length > 2 }
        .map { (it.startsWith("1|")) to it.substring(2) }

private fun saveTodos(p: android.content.SharedPreferences, list: List<Pair<Boolean, String>>) {
    p.edit().putString("items", list.joinToString("\n") { (if (it.first) "1|" else "0|") + it.second }).apply()
}

@Composable
fun TodoScreen() {
    val prefs = LocalContext.current.getSharedPreferences("todo", Context.MODE_PRIVATE)
    var text by remember { mutableStateOf("") }
    var list by remember { mutableStateOf(loadTodos(prefs)) }
    fun commit(n: List<Pair<Boolean, String>>) {
        list = n
        saveTodos(prefs, n)
    }
    Column(Modifier.fillMaxSize().padding(16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = text,
                onValueChange = { text = it },
                modifier = Modifier.weight(1f),
                singleLine = true,
                label = { Text("${t('مهمة جديدة', 'New task')}") }
            )
            Spacer(Modifier.width(8.dp))
            Button(onClick = {
                if (text.isNotBlank()) {
                    commit(list + (false to text.trim()))
                    text = ""
                }
            }) { Text("+") }
        }
        Spacer(Modifier.height(12.dp))
        LazyColumn {
            itemsIndexed(list) { i, item ->
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(
                        checked = item.first,
                        onCheckedChange = { c ->
                            commit(list.mapIndexed { j, x -> if (j == i) (c to x.second) else x })
                        }
                    )
                    Text(
                        item.second,
                        Modifier.weight(1f),
                        textDecoration = if (item.first) TextDecoration.LineThrough else null
                    )
                    TextButton(onClick = { commit(list.filterIndexed { j, _ -> j != i }) }) { Text("x") }
                }
            }
        }
    }
}
`,
  },

  notes: {
    id: 'notes',
    keywords: ['ملاحظات', 'ملاحظه', 'مذكره', 'مذكرات', 'يوميات', 'notes', 'note', 'notepad', 'memo'],
    label: { ar: 'الملاحظات', en: 'Notes' },
    icon: 'N',
    fn: 'NotesScreen',
    kotlin: (t) => String.raw`${COMMON}
@Composable
fun NotesScreen() {
    val prefs = LocalContext.current.getSharedPreferences("notes", Context.MODE_PRIVATE)
    var text by remember { mutableStateOf(prefs.getString("note", "") ?: "") }
    Column(Modifier.fillMaxSize().padding(16.dp)) {
        Text("${t('ملاحظاتي', 'My notes')}", style = MaterialTheme.typography.headlineSmall)
        Spacer(Modifier.height(12.dp))
        OutlinedTextField(
            value = text,
            onValueChange = {
                text = it
                prefs.edit().putString("note", it).apply()
            },
            modifier = Modifier.fillMaxSize(),
            label = { Text("${t('اكتب هنا...', 'Write here...')}") }
        )
    }
}
`,
  },

  calculator: {
    id: 'calculator',
    keywords: ['حاسبه', 'الة حاسبه', 'calculator', 'calc'],
    label: { ar: 'الحاسبة', en: 'Calculator' },
    icon: '=',
    fn: 'CalculatorScreen',
    kotlin: () => String.raw`${COMMON}
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.LayoutDirection

private fun fmt(d: Double): String =
    if (!d.isNaN() && !d.isInfinite() && d == Math.floor(d) && Math.abs(d) < 1e15) d.toLong().toString() else d.toString()

private fun applyOp(a: Double, b: Double, o: String): Double = when (o) {
    "+" -> a + b
    "-" -> a - b
    "×" -> a * b
    "÷" -> if (b == 0.0) Double.NaN else a / b
    else -> b
}

@Composable
fun CalculatorScreen() {
    var display by remember { mutableStateOf("0") }
    var acc by remember { mutableStateOf<Double?>(null) }
    var op by remember { mutableStateOf<String?>(null) }
    var fresh by remember { mutableStateOf(true) }
    val digits = "0123456789"

    fun press(k: String) {
        when {
            k.length == 1 && digits.contains(k) -> {
                display = if (fresh || display == "0") k else display + k
                fresh = false
            }
            k == "." -> {
                if (fresh) {
                    display = "0."
                    fresh = false
                } else if (!display.contains(".")) display += "."
            }
            k == "C" -> {
                display = "0"
                acc = null
                op = null
                fresh = true
            }
            k == "=" -> {
                val a = acc
                val o = op
                if (a != null && o != null) {
                    display = fmt(applyOp(a, display.toDoubleOrNull() ?: 0.0, o))
                    acc = null
                    op = null
                    fresh = true
                }
            }
            else -> {
                val a = acc
                val o = op
                if (a != null && o != null && !fresh) {
                    val r = applyOp(a, display.toDoubleOrNull() ?: 0.0, o)
                    acc = r
                    display = fmt(r)
                } else {
                    acc = display.toDoubleOrNull() ?: 0.0
                }
                op = k
                fresh = true
            }
        }
    }

    val rows = listOf(
        listOf("7", "8", "9", "÷"),
        listOf("4", "5", "6", "×"),
        listOf("1", "2", "3", "-"),
        listOf("0", ".", "=", "+")
    )
    CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Ltr) {
        Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.Bottom) {
            Text(
                display,
                fontSize = 56.sp,
                maxLines = 1,
                textAlign = TextAlign.End,
                modifier = Modifier.fillMaxWidth().padding(vertical = 24.dp)
            )
            rows.forEach { r ->
                Row(Modifier.fillMaxWidth()) {
                    r.forEach { k ->
                        Button(
                            onClick = { press(k) },
                            modifier = Modifier.weight(1f).padding(4.dp).height(64.dp)
                        ) { Text(k, fontSize = 22.sp) }
                    }
                }
            }
            OutlinedButton(onClick = { press("C") }, modifier = Modifier.fillMaxWidth().padding(4.dp)) { Text("C") }
        }
    }
}
`,
  },

  stopwatch: {
    id: 'stopwatch',
    keywords: ['ساعه ايقاف', 'ساعة إيقاف', 'مؤقت', 'توقيت', 'كرونو', 'stopwatch', 'timer', 'chrono'],
    label: { ar: 'ساعة الإيقاف', en: 'Stopwatch' },
    icon: 'T',
    fn: 'StopwatchScreen',
    kotlin: (t) => String.raw`${COMMON}
import kotlinx.coroutines.delay

@Composable
fun StopwatchScreen() {
    var elapsed by remember { mutableLongStateOf(0L) }
    var running by remember { mutableStateOf(false) }
    LaunchedEffect(running) {
        if (running) {
            val start = System.currentTimeMillis() - elapsed
            while (true) {
                elapsed = System.currentTimeMillis() - start
                delay(30)
            }
        }
    }
    val cs = (elapsed / 10) % 100
    val s = (elapsed / 1000) % 60
    val m = elapsed / 60000
    Column(
        Modifier.fillMaxSize().padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text(String.format(java.util.Locale.US, "%02d:%02d.%02d", m, s, cs), fontSize = 56.sp)
        Spacer(Modifier.height(24.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            Button(onClick = { running = !running }) {
                Text(if (running) "${t('إيقاف', 'Stop')}" else "${t('ابدأ', 'Start')}")
            }
            OutlinedButton(onClick = {
                running = false
                elapsed = 0L
            }) { Text("${t('تصفير', 'Reset')}") }
        }
    }
}
`,
  },

  bmi: {
    id: 'bmi',
    keywords: ['كتله الجسم', 'bmi', 'مؤشر الجسم', 'لياقه', 'body mass'],
    label: { ar: 'كتلة الجسم', en: 'BMI' },
    icon: 'B',
    fn: 'BmiScreen',
    kotlin: (t) => String.raw`${COMMON}
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.text.input.KeyboardType

@Composable
fun BmiScreen() {
    var w by remember { mutableStateOf("") }
    var h by remember { mutableStateOf("") }
    val wv = w.toDoubleOrNull()
    val hv = h.toDoubleOrNull()
    val bmi = if (wv != null && hv != null && hv > 0) wv / ((hv / 100) * (hv / 100)) else null
    Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("${t('حاسبة كتلة الجسم', 'BMI calculator')}", style = MaterialTheme.typography.headlineSmall)
        OutlinedTextField(
            value = w, onValueChange = { w = it }, singleLine = true,
            modifier = Modifier.fillMaxWidth(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            label = { Text("${t('الوزن (كغ)', 'Weight (kg)')}") }
        )
        OutlinedTextField(
            value = h, onValueChange = { h = it }, singleLine = true,
            modifier = Modifier.fillMaxWidth(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            label = { Text("${t('الطول (سم)', 'Height (cm)')}") }
        )
        if (bmi != null) {
            val cat = when {
                bmi < 18.5 -> "${t('نحافة', 'Underweight')}"
                bmi < 25 -> "${t('وزن طبيعي', 'Normal')}"
                bmi < 30 -> "${t('وزن زائد', 'Overweight')}"
                else -> "${t('سمنة', 'Obese')}"
            }
            Text(String.format(java.util.Locale.US, "%.1f", bmi), fontSize = 48.sp)
            Text(cat, style = MaterialTheme.typography.titleLarge)
        }
    }
}
`,
  },

  converter: {
    id: 'converter',
    keywords: ['محول', 'تحويل', 'converter', 'convert', 'unit'],
    label: { ar: 'المحوّل', en: 'Converter' },
    icon: '~',
    fn: 'ConverterScreen',
    kotlin: (t) => String.raw`${COMMON}
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.text.input.KeyboardType

private val conversions: List<Pair<String, (Double) -> Double>> = listOf(
    "km → mi" to { v: Double -> v * 0.621371 },
    "mi → km" to { v: Double -> v / 0.621371 },
    "kg → lb" to { v: Double -> v * 2.204623 },
    "lb → kg" to { v: Double -> v / 2.204623 },
    "°C → °F" to { v: Double -> v * 9 / 5 + 32 },
    "°F → °C" to { v: Double -> (v - 32) * 5 / 9 },
    "m → ft" to { v: Double -> v * 3.28084 },
    "ft → m" to { v: Double -> v / 3.28084 }
)

@Composable
fun ConverterScreen() {
    var sel by remember { mutableIntStateOf(0) }
    var input by remember { mutableStateOf("") }
    val v = input.toDoubleOrNull()
    Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("${t('محوّل الوحدات', 'Unit converter')}", style = MaterialTheme.typography.headlineSmall)
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            conversions.forEachIndexed { i, c ->
                FilterChip(selected = sel == i, onClick = { sel = i }, label = { Text(c.first) })
            }
        }
        OutlinedTextField(
            value = input, onValueChange = { input = it }, singleLine = true,
            modifier = Modifier.fillMaxWidth(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            label = { Text("${t('القيمة', 'Value')}") }
        )
        if (v != null) {
            Text(String.format(java.util.Locale.US, "%.4f", conversions[sel].second(v)), fontSize = 40.sp)
        }
    }
}
`,
  },

  dice: {
    id: 'dice',
    keywords: ['نرد', 'زهر', 'عشوائي', 'dice', 'random', 'roll'],
    label: { ar: 'النرد', en: 'Dice' },
    icon: 'D',
    fn: 'DiceScreen',
    kotlin: (t) => String.raw`${COMMON}
@Composable
fun DiceScreen() {
    var value by remember { mutableIntStateOf(1) }
    var rolls by remember { mutableIntStateOf(0) }
    Column(
        Modifier.fillMaxSize().padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text("$value", fontSize = 120.sp)
        Spacer(Modifier.height(16.dp))
        Button(onClick = {
            value = (1..6).random()
            rolls += 1
        }) { Text("${t('ارمِ النرد', 'Roll')}") }
        Spacer(Modifier.height(8.dp))
        Text("${t('عدد الرميات', 'Rolls')}: $rolls")
    }
}
`,
  },

  about: {
    id: 'about',
    keywords: ['عن التطبيق', 'about'],
    label: { ar: 'حول', en: 'About' },
    icon: 'i',
    fn: 'AboutScreen',
    kotlin: (t, spec) => String.raw`${COMMON}
@Composable
fun AboutScreen() {
    Column(
        Modifier.fillMaxSize().padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text("${spec.name}", style = MaterialTheme.typography.headlineMedium)
        Spacer(Modifier.height(12.dp))
        Text("${t('تم إنشاؤه بواسطة بنّاء التطبيقات', 'Generated by App Builder')}")
    }
}
`,
  },
};

module.exports = { COMPONENTS, COMMON };
