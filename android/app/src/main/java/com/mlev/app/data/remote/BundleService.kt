package com.mlev.app.data.remote

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import java.io.IOException
import java.net.HttpURLConnection
import java.net.SocketTimeoutException
import java.net.URL

/**
 * Fetches prediction bundles.
 *
 * The default source is a published URL — GitHub Pages or a release asset — so
 * the app works anywhere with a connection and never needs the machine that
 * trained the models. Pointing it at a computer on the local network is still
 * supported for testing an export before publishing it.
 *
 * Uses HttpURLConnection rather than adding an HTTP client: one GET of a small
 * JSON file does not justify the dependency.
 */
class BundleService(private val json: Json = DEFAULT_JSON) {

    sealed interface Result<out T> {
        data class Success<T>(val value: T) : Result<T>
        data class Failure(val reason: String, val recoverable: Boolean = true) : Result<Nothing>
    }

    suspend fun fetchBundle(baseUrl: String, sport: String): Result<BundleDto> =
        fetch(joinUrl(baseUrl, "$sport.json")) { body ->
            val dto = json.decodeFromString<BundleDto>(body)
            if (dto.schema !in SUPPORTED_SCHEMAS) {
                return@fetch Result.Failure(
                    "This bundle uses format version ${dto.schema}, and this app " +
                        "understands ${SUPPORTED_SCHEMAS.joinToString()}. Update the app.",
                    recoverable = false,
                )
            }
            if (dto.sport != sport) {
                return@fetch Result.Failure("Expected a $sport bundle but got ${dto.sport}.", false)
            }
            Result.Success(dto)
        }

    suspend fun fetchIndex(baseUrl: String): Result<IndexDto> =
        fetch(joinUrl(baseUrl, "index.json")) { Result.Success(json.decodeFromString<IndexDto>(it)) }

    private suspend fun <T> fetch(
        url: String,
        parse: (String) -> Result<T>,
    ): Result<T> = withContext(Dispatchers.IO) {
        var connection: HttpURLConnection? = null
        try {
            connection = (URL(url).openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = CONNECT_TIMEOUT_MS
                readTimeout = READ_TIMEOUT_MS
                setRequestProperty("Accept", "application/json")
                instanceFollowRedirects = true
            }
            when (val code = connection.responseCode) {
                in 200..299 -> {
                    val body = connection.inputStream.bufferedReader().use { it.readText() }
                    if (body.isBlank()) Result.Failure("The server returned an empty response.")
                    else parse(body)
                }
                404 -> Result.Failure(
                    "No bundle published at that address yet. If you just set this " +
                        "up, the first export may not have run.",
                )
                in 500..599 -> Result.Failure("The server is having trouble (HTTP $code).")
                else -> Result.Failure("Unexpected response (HTTP $code).")
            }
        } catch (e: SocketTimeoutException) {
            Result.Failure("Timed out reaching $url.")
        } catch (e: IOException) {
            Result.Failure("Could not reach $url. Check your connection.")
        } catch (e: IllegalArgumentException) {
            Result.Failure("That address is not a valid URL.", recoverable = false)
        } catch (e: Exception) {
            // A malformed payload lands here; treat it as unrecoverable so the
            // app keeps the last good bundle rather than replacing it with junk.
            Result.Failure("The bundle could not be read: ${e.message}", recoverable = false)
        } finally {
            connection?.disconnect()
        }
    }

    private fun joinUrl(base: String, file: String): String =
        if (base.endsWith("/")) base + file else "$base/$file"

    companion object {
        private const val CONNECT_TIMEOUT_MS = 10_000
        private const val READ_TIMEOUT_MS = 20_000
        val SUPPORTED_SCHEMAS = setOf(1)
        val DEFAULT_JSON = Json { ignoreUnknownKeys = true; isLenient = true }
    }
}
