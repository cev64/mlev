package com.mlev.app.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.mlev.app.ui.theme.EvColors

/** A probability, as a bar plus its number. The bar makes a column scannable. */
@Composable
fun ProbabilityBar(
    probability: Double,
    modifier: Modifier = Modifier,
    label: String = "",
) {
    val fraction = probability.coerceIn(0.0, 1.0).toFloat()
    Row(
        modifier = modifier.semantics {
            contentDescription = "$label ${"%.1f".format(probability * 100)} percent"
        },
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Box(
            Modifier
                .weight(1f)
                .height(6.dp)
                .clip(RoundedCornerShape(3.dp))
                .background(MaterialTheme.colorScheme.surfaceVariant)
        ) {
            Box(
                Modifier
                    .fillMaxWidth(fraction)
                    .height(6.dp)
                    .clip(RoundedCornerShape(3.dp))
                    .background(MaterialTheme.colorScheme.primary)
            )
        }
        Text(
            text = "%.1f%%".format(probability * 100),
            style = MaterialTheme.typography.bodyMedium,
            fontFamily = FontFamily.Monospace,
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier.width(62.dp),
            textAlign = TextAlign.End,
        )
    }
}

/** Expected value, coloured only by its sign. */
@Composable
fun EvBadge(value: Double?, modifier: Modifier = Modifier) {
    if (value == null) {
        Text("—", style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = modifier)
        return
    }
    val positive = value > 0
    Text(
        text = "%s%.2f".format(if (positive) "+" else "", value),
        style = MaterialTheme.typography.titleSmall,
        fontFamily = FontFamily.Monospace,
        fontWeight = FontWeight.Bold,
        color = if (positive) EvColors.positive() else EvColors.negative(),
        modifier = modifier.semantics {
            contentDescription = if (positive) "positive expected value" else "negative expected value"
        },
    )
}

/** A short labelled statistic. */
@Composable
fun StatLine(label: String, value: String, modifier: Modifier = Modifier) {
    Row(modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(label, style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, style = MaterialTheme.typography.bodySmall,
            fontWeight = FontWeight.SemiBold, fontFamily = FontFamily.Monospace)
    }
}

/** Boxed note. [tone] picks neutral, caution or error styling. */
enum class NoteTone { INFO, CAUTION, ERROR }

@Composable
fun NoteCard(text: String, tone: NoteTone = NoteTone.INFO, modifier: Modifier = Modifier) {
    val container = when (tone) {
        NoteTone.INFO -> MaterialTheme.colorScheme.primaryContainer
        NoteTone.CAUTION -> MaterialTheme.colorScheme.tertiaryContainer
        NoteTone.ERROR -> MaterialTheme.colorScheme.errorContainer
    }
    val content = when (tone) {
        NoteTone.INFO -> MaterialTheme.colorScheme.onPrimaryContainer
        NoteTone.CAUTION -> MaterialTheme.colorScheme.onTertiaryContainer
        NoteTone.ERROR -> MaterialTheme.colorScheme.onErrorContainer
    }
    Card(
        modifier = modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = container),
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.bodySmall,
            color = content,
            modifier = Modifier.padding(12.dp),
        )
    }
}

/** Section heading inside a card. */
@Composable
fun SectionLabel(text: String, trailing: String? = null, modifier: Modifier = Modifier) {
    Row(
        modifier.fillMaxWidth().padding(top = 10.dp, bottom = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(
            text.uppercase(),
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        if (trailing != null) {
            Text(
                trailing,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier
                    .clip(RoundedCornerShape(8.dp))
                    .background(MaterialTheme.colorScheme.surfaceVariant)
                    .padding(horizontal = 6.dp, vertical = 1.dp),
            )
        }
    }
}
